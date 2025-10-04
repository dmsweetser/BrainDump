import os
import re
import logging
from typing import List, Dict, Any, Optional

import xml.etree.ElementTree as ET
from lib.config import Config


class StringParser:
    @staticmethod
    def parse_custom_format(content: str) -> List[Dict[str, Any]]:
        try:
            if "<tool_call>" in content:
                content = content.split("<tool_call>")[1]
            content = re.sub(r'^.*?\[aibuilder_change', '[aibuilder_change', content, flags=re.DOTALL)
            changes = []
            change_blocks = re.finditer(
                r'\[aibuilder_change\s+file\s*=\s*"([^"]+)"\](.*?)(?=\[aibuilder_change|$)',
                content,
                re.DOTALL
            )
            for block in change_blocks:
                file = block.group(1)
                actions = StringParser._parse_actions(block.group(2))
                changes.append({'file': file, 'actions': actions})
            return changes
        except Exception as e:
            logging.error(f"Error parsing custom format: {e}")
            raise

    @staticmethod
    def _parse_actions(content: str) -> List[Dict[str, Any]]:
        try:
            actions = []
            action_blocks = re.finditer(
                r'\[aibuilder_action\s+type\s*=\s*"([^"]+)"\](.*?)\[aibuilder_end_action\]',
                content,
                re.DOTALL
            )
            for action_block in action_blocks:
                action_type = action_block.group(1)
                action_content = action_block.group(2)
                if action_type == 'replace_section':
                    action = StringParser._parse_replace_section_action(action_content)
                    if action:
                        actions.append(action)
                # Ignore other action types
            return actions
        except Exception as e:
            logging.error(f"Error parsing actions: {e}")
            raise

    @staticmethod
    def _parse_replace_section_action(content: str) -> Optional[Dict[str, Any]]:
        try:
            original_content_pattern = r'\[aibuilder_original_content\](.*?)\[aibuilder_end_original_content\]'
            file_content_pattern = r'\[aibuilder_file_content\](.*?)\[aibuilder_end_file_content\]'
            original_content_match = re.search(original_content_pattern, content, re.DOTALL)
            file_content_match = re.search(file_content_pattern, content, re.DOTALL)
            if original_content_match and file_content_match:
                return {
                    'action': 'replace_section',
                    'original_content': original_content_match.group(1).strip(),
                    'file_content': file_content_match.group(1).strip().split('\n')
                }
            return None
        except Exception as e:
            logging.error(f"Error parsing replace section action: {e}")
            raise


class StringModifier:
    @staticmethod
    def apply_modifications(content: str, changes: List[Dict[str, Any]], dry_run: bool = False) -> str:
        modified_content = content
        for change in changes:
            file = change['file']
            logging.info(f"Processing file: {file}")

            for action in change['actions']:
                try:
                    if dry_run:
                        logging.info(f"Dry run: Would apply action {action['action']} to content")
                    else:
                        modified_content = StringModifier._apply_action(modified_content, action)
                except Exception as e:
                    logging.error(f"Error applying modifications: {e}")
        return modified_content

    @staticmethod
    def _apply_action(content: str, action: Dict[str, Any]) -> bool:
        try:
            action_type = action['action']
            if action_type == 'replace_section':
                return StringModifier._replace_section(content, action['original_content'], action['file_content'])
            return content
        except Exception as e:
            logging.error(f"Error applying action: {e}")
            raise

    @staticmethod
    def _replace_section(content: str, original_content: str, new_content: List[str]) -> bool:
        try:
            new_section_str = '\n'.join(new_content)
            if original_content in content:
                modified_content = content.replace(original_content, new_section_str)
                logging.info("Replaced section in content")
                return modified_content
            else:
                logging.warning("Original content not found in content")
                return content
        except Exception as e:
            logging.error(f"Error replacing section: {e}")
            return content


class AIBuilder:
    def __init__(self):
        self.response_file = "current_response.txt"
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler("utility.log"),
                logging.StreamHandler()
            ]
        )

    def run(self, current_document: str, instructions: str) -> str:
        try:
            prompt = f"""
You are a document revision assistant. You will receive a document and a list of new notes.

Your task: **Only** update the document by replacing **sections** that are outdated or need restructuring based on the new notes.

Rules:
1. **Never** create new files.
2. **Never** remove files.
3. **Never** replace entire files.
4. **Only** use `replace_section` to update specific sections of the document.
5. Match the original section content **exactly** (including whitespace and formatting).
6. Do **not** change any content outside the updated sections.
7. If a section is not affected, **do not** modify it.
8. Output **only** the `replace_section` actions in the required format.

Example format:
[aibuilder_change file="document"]
[aibuilder_action type="replace_section"]
[aibuilder_original_content]
<h2>Introduction</h2>
<p>This is the original intro.</p>
[aibuilder_end_original_content]
[aibuilder_file_content]
<h2>Introduction</h2>
<p>This is the updated intro with new context.</p>
<a href="#new-section">Go to new section</a>
[aibuilder_end_file_content]
[aibuilder_end_action]

Document:
{current_document}

New Notes:
{instructions}

Respond **only** in the required format. No commentary. No explanations. No markdown. Just the actions.
"""
            use_local_model = Config.USE_LOCAL_MODEL
            if use_local_model:
                model_path = Config.MODEL_PATH
                if not model_path:
                    logging.error("MODEL_PATH environment variable not set for local model.")
                    raise ValueError("MODEL_PATH environment variable not set.")
                from llama_cpp import Llama
                llm = Llama(
                    model_path=model_path,
                    n_ctx=Config.CONTEXT_SIZE
                )
                response_content = ""
                for response in llm.create_completion(
                    prompt,
                    temperature=Config.TEMPERATURE,
                    top_p=Config.TOP_P,
                    top_k=Config.TOP_K,
                    min_p=Config.MIN_P,
                    max_tokens=Config.MAX_TOKENS,
                    stream=True
                ):
                    token = response['choices'][0]['text']
                    response_content += token
                    with open(self.response_file, 'a', encoding='utf-8') as f:
                        f.write(response_content)
            else:
                from azure.ai.inference import ChatCompletionsClient
                from azure.core.credentials import AzureKeyCredential
                client = ChatCompletionsClient(
                    endpoint=Config.ENDPOINT,
                    credential=AzureKeyCredential(Config.API_KEY),
                    api_version="2024-05-01-preview"
                )
                response = client.complete(
                    stream=True,
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant."},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=Config.MAX_TOKENS,
                    model=Config.MODEL_NAME
                )
                response_content = ""
                for update in response:
                    if update.choices and len(update.choices) > 0:
                        content = update.choices[0].get("delta", {}).get("content", "")
                        if content is not None:
                            response_content += content
                    else:
                        break

            logging.info("Successfully obtained AI response.")
            with open(self.response_file, 'w', encoding='utf-8') as f:
                f.write(response_content)

            # Parse the response and apply changes to the document
            changes = StringParser.parse_custom_format(response_content)
            modified_document = StringModifier.apply_modifications(current_document, changes, dry_run=False)


            return modified_document

        except Exception as e:
            logging.error(f"AI Builder error: {e}", exc_info=True)
            raise