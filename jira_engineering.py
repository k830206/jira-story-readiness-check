import openai
import json
import logging
import requests
from requests.auth import HTTPBasicAuth
import json
from jsonpath_ng import parse
import logging
import os

logging.basicConfig(level=logging.INFO)

# Set Jira credential
JIRA_KEY = str(os.environ['JIRA_KEY'])
JIRA_AUTH = HTTPBasicAuth(str(os.environ['JIRA_USERNAME']), JIRA_KEY)
JIRA_URL_PREFIX = str(os.environ['URL_PREFIX'])
JIRA_HEADER = {
    "Accept": "application/json",
    "Content-Type": "application/json"
}

# Set OpenAI credential
openai.api_key = str(os.environ['OPENAI_KEY'])


JSON_CODE_BLOCK_PREFIX = '```json'
JSON_CODE_BLOCK_SUFFIX = '```'
ADDITIONAL_REQUEST_KEY = 'request'
RESULT_KEY = 'result'
READINESS_KEY = 'story_readiness'
MAX_REQUEST = 5         # Set a number of maximum addtional requsts
PROMPTS = {}

# Jira user story information with JSON format
def get_story_detail(story_number):
    request_urls = f"{JIRA_URL_PREFIX}/{story_number}"
    response = requests.get(request_urls, headers=JIRA_HEADER, auth=JIRA_AUTH)

    if response.status_code == 200:
        data = response.json()
        return json.dumps(data)
    else:
        logging.error(f"Failed to retrieve issues. Status code: {response.status_code}, Error: {response.text}")
        return '{}'

# Put a comment in Jira user story
def add_comment(story_number, message):
    request_url = f"{JIRA_URL_PREFIX}/{story_number}/comment"
    payload = json.dumps({
        "body": {
            "content": [
                {
                    "content": [
                        {
                            "text": message,
                            "type": "text"
                        }
                    ],
                    "type": "paragraph"
                }
            ],
            "type": "doc",
            "version": 1            
        }
    })
    
    response = requests .post(request_url, data=payload, headers=JIRA_HEADER, auth=JIRA_AUTH)

    if response.status_code == 201:
        return True
    else:
        logging.error(f"Failed to retrieve issues. Status code: {response.status_code}, Error: {response.text}")
        return False

# Retrieve information from a Jira server then parse it with JSON Path
def get_extra_requests(reqeust_urls):
    results = dict()

    for url_obj in reqeust_urls:
        url_str = url_obj['url']
        response = requests.get(url_str, headers=JIRA_HEADER, auth=JIRA_AUTH)

        if response.status_code == 200:
            data = response.json()

            jsonpath_list = list(map(lambda x : x.strip(), str(url_obj['jsonpath']).split(',')))
            results[url_str] = {}

            for jsonpath_str in jsonpath_list:
                jsonpath_expr = parse(jsonpath_str)
                results[url_str][jsonpath_str] = [match.value for match in jsonpath_expr.find(data)]
        else:
            results[url_str] = f"Failed to retrieve issues. Status code: {response.status_code}, Error: {response.text}"

    return json.dumps(results)

# Load prompts from files
def load_prompts():
    with open('first_prompt.txt', 'r') as file_obj:
        PROMPTS['FIRST'] = file_obj.read()
    
    with open('repeat_prompt.txt', 'r') as file_obj:
        PROMPTS['REPEAT'] = file_obj.read()    

# Extract JSON code block from a markdown file
def extract_json_block(response_str):
    prefix = '```json'
    suffix = '```'
    
    if prefix in response_str:
        response_str = response_str[response_str.index(prefix) + len(prefix):]
        response_str = response_str[:response_str.index(suffix)]
        
        return json.loads(response_str)
    else:
        return {}

# Convert OpenAI generated JSON message to a plain text
def convert_to_plain_message(response_str):
    response_lines = []
    checker_json = extract_json_block(response_str)
    result_obj = checker_json['result']
    story_readiness = checker_json['story_readiness']
    required_info = checker_json['extra_information_required'] if 'extra_information_required' in checker_json else []
    
    response_lines.append(f"Ready to develop: {str(story_readiness)}")
    
    if (not story_readiness) and len(required_info) > 0:
        response_lines.append('')
        response_lines.append('Required informtion to make this story ready: ')
        
        for it, info_str in enumerate(required_info):
            response_lines.append(f"{str(it + 1)}. {info_str}")
    
    response_lines.append('')
    response_lines.append("Revised story content:")
    response_lines.append("Narrative:")
    response_lines.append(result_obj['narrative'])
    response_lines.append('')
    response_lines.append("Scope:")
    response_lines.append(result_obj['scope'])
    response_lines.append('')
    response_lines.append("Acceptance Criteria:")
    
    for it, ac_str in enumerate(result_obj['acceptance_criteria']):
        response_lines.append(f"{str(it + 1)}. {ac_str}")    
    
    response_lines.append('')
    response_lines.append(f"Estimate point(s): {str(result_obj['estimated_points'])}")
    response_lines.append(f"A basis for the point: {str(result_obj['reason_for_estimated_points'])}")
    
    if 'related_stories' in result_obj and len(result_obj['related_stories']) > 0:
        response_lines.append('')
        story_numbers = ", ".join(result_obj['related_stories'])
        response_lines.append(f"Related stories: {story_numbers}")
    
    return '\n'.join(response_lines)    

# Call OpenAI APIs to generate a story readiness
def get_story_readiness(story_number, log_to_file=False):
    # Set a system prompt
    system_prompt = {
        "role": "system",
        "content": PROMPTS['FIRST']
    }
    
    total_request_count = 0

    # Initialise total tokens
    total_tokens = 0
    total_input_tokens = 0
    total_output_tokens = 0
    
    # Set an initial conversation messages
    conversation_messages = [system_prompt]
    
    while total_request_count == 0 or (ADDITIONAL_REQUEST_KEY in communication and len(communication[ADDITIONAL_REQUEST_KEY]) > 0 and total_request_count < MAX_REQUEST):
        logging.info(f"OpenAI API Request #{total_request_count + 1}")
        # Set an user prompt        
        analysis_user_prompt = {"role": "user"}
        
        if total_request_count == 0:
            analysis_user_prompt["content"] = get_story_detail(story_number)
        else:
            api_query_result_str = get_extra_requests(communication[ADDITIONAL_REQUEST_KEY])
            analysis_user_prompt["content"] = f"{PROMPTS['REPEAT']}\n{api_query_result_str}" 
        
        conversation_messages.append(analysis_user_prompt)
        total_request_count += 1
    
        # Request to OpenAI
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=conversation_messages,
            temperature=0.0
        )
    
        repsonse_message = response.choices[0].message['content']    
        communication = extract_json_block(repsonse_message)
    
        # Accumulate the conversations
        conversation_messages.append({
            "role": response.choices[0].message['role'],
            "content": repsonse_message
        })    
    
        # Update total tokens
        usage = response['usage']
        total_input_tokens += usage['prompt_tokens']
        total_output_tokens += usage['completion_tokens']
        total_tokens += usage['total_tokens']

    estimated_input_price = (total_input_tokens / (10 ** 6)) * 5
    estimated_output_price = (total_output_tokens / (10 ** 6)) * 15
    estimated_price = estimated_input_price + estimated_output_price

    logging.info(f"Total tokens to generate a report: {total_tokens}")
    logging.info(f"Total input tokens to generate a report: {total_input_tokens}")
    logging.info(f"Total output tokens to generate a report: {total_output_tokens}")
    logging.info(f"Price decomposition: USD {estimated_input_price} [Input] + USD {estimated_output_price} [Output] = USD {estimated_price}")
    
    if log_to_file:
        md_logs = []
        
        for message_obj in conversation_messages:
            md_logs.append(f"# {message_obj['role']}")
            md_logs.append(message_obj['content'])
            md_logs.append('')
        
        with open(f"{story_number}.md", 'w') as file_obj:
            file_obj.write('\n'.join(md_logs))
    
    return conversation_messages[-1]['content']


if __name__ == '__main__':
    load_prompts()

    story_number = 'KAN-2'
    result_str = get_story_readiness(story_number, True)
    
    plain_text = convert_to_plain_message(result_str)
    add_result = add_comment(story_number, plain_text)
    
    if add_result:
        logging.info(f"A revised context is posted on a comment in {story_number} story.")
    else:
        logging.error(f"Fail to post a comment in {story_number}")
