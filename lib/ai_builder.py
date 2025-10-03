import os
import re
import logging
import shutil
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional
from pathlib import Path
from config import Config

class FileParser:
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
                actions = FileParser._parse_actions(block.group(2))
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
                if action_type == 'create_file':
                    action = FileParser._parse_create_action(action_content)
                elif action_type == 'remove_file':
                    action = {'action': 'remove_file'}
                elif action_type == 'replace_file':
                    action = FileParser._parse_replace_file_action(action_content)
                elif action_type == 'replace_section':
                    action = FileParser._parse_replace_section_action(action_content)
                else:
                    continue
                if action:
                    actions.append(action)
            return actions
        except Exception as e:
            logging.error(f"Error parsing actions: {e}")
            raise

    @staticmethod
    def _parse_create_action(content: str) -> Optional[Dict[str, Any]]:
        try:
            file_content_pattern = r'\[aibuilder_file_content\](.*?)\[aibuilder_end_file_content\]'
            file_content_match = re.search(file_content_pattern, content, re.DOTALL)
            if file_content_match:
                return {
                    'action': 'create_file',
                    'file_content': file_content_match.group(1).strip().split('\n')
                }
            return None
        except Exception as e:
            logging.error(f"Error parsing create action: {e}")
            raise

    @staticmethod
    def _parse_replace_file_action(content: str) -> Optional[Dict[str, Any]]:
        try:
            file_content_pattern = r'\[aibuilder_file_content\](.*?)\[aibuilder_end_file_content\]'
            file_content_match = re.search(file_content_pattern, content, re.DOTALL)
            if file_content_match:
                return {
                    'action': 'replace_file',
                    'file_content': file_content_match.group(1).strip().split('\n')
                }
            return None
        except Exception as e:
            logging.error(f"Error parsing replace file action: {e}")
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

class FileModifier:
    @staticmethod
    def apply_modifications(changes: List[Dict[str, Any]], dry_run: bool = False) -> List[Dict[str, Any]]:
        incomplete_actions = []
        for change in changes:
            filepath = change['file']
            backup_filepath = f"{filepath}.bak"
            logging.info(f"Processing file: {filepath}")
            if not dry_run:
                try:
                    if os.path.exists(filepath):
                        shutil.copy2(filepath, backup_filepath)
                        logging.info(f"Created backup: {backup_filepath}")
                except Exception as e:
                    logging.error(f"Could not back up file: {filepath}: {e}")
            for action in change['actions']:
                try:
                    if dry_run:
                        logging.info(f"Dry run: Would apply action {action['action']} to {filepath}")
                    else:
                        if not FileModifier._apply_action(filepath, action):
                            incomplete_actions.append({'file': filepath, 'action': action})
                except Exception as e:
                    logging.error(f"Error applying modifications to {filepath}: {e}")
                    incomplete_actions.append({'file': filepath, 'action': action})
                    if not dry_run and os.path.exists(backup_filepath):
                        shutil.copy2(backup_filepath, filepath)
                        logging.info(f"Restored backup for {filepath}")
        return incomplete_actions

    @staticmethod
    def _apply_action(filepath: str, action: Dict[str, Any]) -> bool:
        try:
            action_type = action['action']
            os.makedirs(os.path.dirname(filepath), exist_ok=True)

            if action_type == 'create_file':
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write("\n".join(action['file_content']) + "\n")
                logging.info(f"Created/Replaced: {filepath}")
                return True
            elif action_type == 'remove_file':
                if os.path.isfile(filepath):
                    os.remove(filepath)
                    logging.info(f"Removed: {filepath}")
                    return True
                else:
                    logging.warning(f"File not found: {filepath}")
                    return False
            elif action_type == 'replace_file':
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write("\n".join(action['file_content']) + "\n")
                logging.info(f"Replaced entire content of: {filepath}")
                return True
            elif action_type == 'replace_section':
                return FileModifier._replace_section(filepath, action['original_content'], action['file_content'])
            return False
        except Exception as e:
            logging.error(f"Error applying action: {e}")
            raise

    @staticmethod
    def _replace_section(filepath: str, original_content: str, new_content: List[str]) -> bool:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            new_section_str = '\n'.join(new_content)
            if original_content in content:
                modified_content = content.replace(original_content, new_section_str)
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(modified_content)
                logging.info(f"Replaced section in: {filepath}")
                return True
            else:
                logging.warning(f"Original content not found in: {filepath}")
                return False
        except Exception as e:
            logging.error(f"Error replacing section: {e}")
            raise

class ActionManager:
    @staticmethod
    def save_actions(actions: List[Dict[str, Any]], filepath: str) -> None:
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                for action in actions:
                    f.write(f"File: {action['file']}\n")
                    f.write(f"Action: {action['action']['action']}\n")
                    if action['action']['action'] in ['create_file', 'replace_file', 'replace_section']:
                        f.write("Content:\n")
                        f.write("\n".join(action['action']['file_content']) + "\n")
                    if action['action']['action'] == 'replace_section':
                        f.write(f"Original Content:\n{action['action']['original_content']}\n")
                    f.write("\n")
            logging.info(f"Saved actions to {filepath}")
        except Exception as e:
            logging.error(f"Error saving actions: {e}")
            raise

    @staticmethod
    def load_actions(filepath: str) -> List[Dict[str, Any]]:
        try:
            actions = []
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
                action_blocks = re.finditer(
                    r'File: (.*?)\nAction: (.*?)\n(?:Content:\n(.*?)(?=\nFile:|\Z))?(?:Original Content:\n(.*?)(?=\nFile:|\Z))?',
                    content,
                    re.DOTALL
                )
                for block in action_blocks:
                    file = block.group(1)
                    action_type = block.group(2)
                    file_content = block.group(3).strip().split('\n') if block.group(3) else []
                    original_content = block.group(4).strip() if block.group(4) else None
                    action = {'action': action_type}
                    if action_type in ['create_file', 'replace_file', 'replace_section']:
                        action['file_content'] = file_content
                    if action_type == 'replace_section':
                        action['original_content'] = original_content
                    actions.append({'file': file, 'action': action})
            logging.info(f"Loaded actions from {filepath}")
            return actions
        except Exception as e:
            logging.error(f"Error loading actions: {e}")
            raise

class AIBuilder:
    def __init__(self, root_directory: Path):
        self.root_directory = root_directory
        self.ai_builder_dir = Config.get_ai_builder_dir(root_directory)
        self.response_file = os.path.join(self.ai_builder_dir, "current_response.txt")
        self.output_file = os.path.join(self.ai_builder_dir, "output.txt")
        self.actions_file = os.path.join(self.ai_builder_dir, "actions.txt")
        os.makedirs(self.ai_builder_dir, exist_ok=True)
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(Config.get_log_file_path(root_directory)),
                logging.StreamHandler()
            ]
        )

    def run(self, current_code: str, instructions: str) -> str:
        try:
            config_path = os.path.join(self.ai_builder_dir, "user_config.xml")
            if not os.path.exists(config_path):
                default_config = """<?xml version="1.0" encoding="UTF-8"?>
<config>
    <iterations>1</iterations>
    <mode>exclude</mode>
    <patterns>
        <pattern>package-lock.json</pattern>
        <pattern>output.txt</pattern>
        <pattern>full_request.txt</pattern>
        <pattern>full_response.txt</pattern>
        <pattern>instructions.txt</pattern>
        <pattern>changes.patch</pattern>
        <pattern>.git</pattern>
        <pattern>utility.log</pattern>
        <pattern>.png</pattern>
        <pattern>.exe</pattern>
        <pattern>.ico</pattern>
        <pattern>.webp</pattern>
        <pattern>.gguf</pattern>
    </patterns>
</config>"""
                with open(config_path, 'w', encoding='utf-8') as f:
                    f.write(default_config)
                logging.warning("Created default user_config.xml")

            config = ET.parse(config_path).getroot()
            mode = config.find('mode').text
            patterns = [p.text for p in config.findall('patterns/pattern')]

            prompt = f"""
Generate a line-delimited format file that describes file modifications to apply using the `create_file`, `remove_file`, `replace_file`, and `replace_section` action types.
Ensure all content is provided using line-delimited format-compatible entities.
Focus on small, specific sections of code rather than large blocks.
Ensure you do not omit any existing code and only modify the sections specified.
Available operations:
1. `create_file`:
    - `file_content`: List of strings (lines of the file content)
2. `remove_file`:
    - No additional parameters needed.
3. `replace_file`:
    - `file_content`: List of strings (lines of the new file content)
    - The revision must be entirely complete
4. `replace_section`:
    - `original_content`: The original content in the file
    - `file_content`: List of strings (lines of the new file content to replace the original content)
Example output format:
[aibuilder_change file="new_file.py"]
[aibuilder_action type="create_file"]
[aibuilder_file_content]
# Content line 1 with whitespace preserved
\t# Content line 2 with whitespace preserved
\t# Content line 3 with whitespace preserved
[aibuilder_end_file_content]
[aibuilder_end_action]
[aibuilder_change file="old_file.py"]
[aibuilder_action type="remove_file"]
[aibuilder_end_action]
[aibuilder_change file="file_to_replace.py"]
[aibuilder_action type="replace_file"]
[aibuilder_file_content]
# New content line 1 with whitespace preserved
\t# New content line 2 with whitespace preserved
\t# New content line 3 with whitespace preserved
[aibuilder_end_file_content]
[aibuilder_end_action]
[aibuilder_change file="file_to_modify.py"]
[aibuilder_action type="replace_section"]
[aibuilder_original_content]
# Original content line 1
\t# Original content line 2
[aibuilder_end_original_content]
[aibuilder_file_content]
# New content line 1 with whitespace preserved
\t# New content line 2 with whitespace preserved
\t# New content line 3 with whitespace preserved
[aibuilder_end_file_content]
[aibuilder_end_action]
Generate modifications logically based on the desired changes.
Current code:
{current_code}
Instructions:
{instructions}
Reply ONLY in the specified format with no commentary. THAT'S AN ORDER, SOLDIER!
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

            return response_content

        except Exception as e:
            logging.error(f"AI Builder error: {e}", exc_info=True)
            raise