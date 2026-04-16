"""
LLM Client abstraction layer

Provides a unified interface for both AWS Bedrock and OpenAI-compatible APIs.
Converts between Bedrock's converse API format and OpenAI's chat completion format.
"""

import json
import logging
from typing import Any
from app.config import LLM_PROVIDER, AWS_REGION, BEDROCK_MODEL, OPENAI_BASE_URL, OPENAI_API_KEY, OPENAI_MODEL

logger = logging.getLogger(__name__)


class LLMClient:
    """Unified LLM client supporting both Bedrock and OpenAI-compatible APIs."""

    def __init__(self):
        self.provider = LLM_PROVIDER

        if self.provider == "bedrock":
            import boto3
            from botocore.config import Config
            self.client = boto3.client(
                "bedrock-runtime",
                region_name=AWS_REGION,
                config=Config(read_timeout=300, connect_timeout=10),
            )
            self.model_id = BEDROCK_MODEL
        else:
            from openai import OpenAI
            import httpx

            # Create HTTP client with longer timeouts and SSL verification disabled for corporate proxies
            http_client = httpx.Client(
                timeout=httpx.Timeout(300.0, connect=60.0),
                verify=False,  # Disable SSL verification for corporate environments
            )

            self.client = OpenAI(
                base_url=OPENAI_BASE_URL,
                api_key=OPENAI_API_KEY,
                http_client=http_client,
            )
            self.model_id = OPENAI_MODEL
            logger.info(f"Initialized OpenAI client with base_url={OPENAI_BASE_URL}, model={OPENAI_MODEL}")

    def converse(
        self,
        system: list[dict[str, str]],
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 8192,
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        """
        Unified converse interface.

        Takes Bedrock-style parameters and returns Bedrock-style response format
        regardless of the underlying provider.
        """
        if self.provider == "bedrock":
            return self._converse_bedrock(system, messages, tools, max_tokens, temperature)
        else:
            return self._converse_openai(system, messages, tools, max_tokens, temperature)

    def _converse_bedrock(
        self,
        system: list[dict[str, str]],
        messages: list[dict],
        tools: list[dict],
        max_tokens: int,
        temperature: float,
    ) -> dict:
        """Call AWS Bedrock using native converse API."""
        response = self.client.converse(
            modelId=self.model_id,
            system=system,
            messages=messages,
            toolConfig={"tools": tools},
            inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
        )
        return response

    def _converse_openai(
        self,
        system: list[dict[str, str]],
        messages: list[dict],
        tools: list[dict],
        max_tokens: int,
        temperature: float,
    ) -> dict:
        """
        Call OpenAI-compatible API and convert response to Bedrock format.

        Converts from Bedrock's converse format to OpenAI's chat completion format,
        then converts the response back to Bedrock format.
        """
        try:
            # Convert system messages
            openai_messages = []
            for sys_msg in system:
                openai_messages.append({
                    "role": "system",
                    "content": sys_msg["text"]
                })

            # Convert conversation messages
            for msg in messages:
                role = msg["role"]
                content = msg.get("content", [])

                # Handle text and tool use content
                if isinstance(content, list):
                    converted_content = []
                    tool_calls = []

                    for block in content:
                        if "text" in block:
                            converted_content.append(block["text"])
                        elif "toolUse" in block:
                            # Convert Bedrock toolUse to OpenAI tool_calls
                            tool_use = block["toolUse"]
                            tool_calls.append({
                                "id": tool_use["toolUseId"],
                                "type": "function",
                                "function": {
                                    "name": tool_use["name"],
                                    "arguments": json.dumps(tool_use["input"])
                                }
                            })
                        elif "toolResult" in block:
                            # Handle tool results (user role with tool results)
                            tool_result = block["toolResult"]
                            result_content = ""
                            for result_block in tool_result.get("content", []):
                                if "text" in result_block:
                                    result_content += result_block["text"]

                            # OpenAI expects tool results as separate messages with role "tool"
                            openai_messages.append({
                                "role": "tool",
                                "tool_call_id": tool_result["toolUseId"],
                                "content": result_content
                            })
                            continue

                    # Build the message
                    msg_dict = {"role": role}
                    if converted_content:
                        msg_dict["content"] = "\n".join(converted_content)
                    if tool_calls:
                        msg_dict["tool_calls"] = tool_calls

                    if converted_content or tool_calls:
                        openai_messages.append(msg_dict)
                else:
                    openai_messages.append({
                        "role": role,
                        "content": str(content)
                    })

            # Convert tools to OpenAI format
            openai_tools = []
            for tool in tools:
                if "toolSpec" in tool:
                    spec = tool["toolSpec"]
                    openai_tools.append({
                        "type": "function",
                        "function": {
                            "name": spec["name"],
                            "description": spec.get("description", ""),
                            "parameters": spec.get("inputSchema", {}).get("json", {})
                        }
                    })

            # Make OpenAI API call
            logger.info(f"Calling OpenAI API: model={self.model_id}, messages={len(openai_messages)}, tools={len(openai_tools)}")
            response = self.client.chat.completions.create(
                model=self.model_id,
                messages=openai_messages,
                tools=openai_tools if openai_tools else None,
                max_tokens=max_tokens,
                temperature=temperature,
            )

            # Convert OpenAI response to Bedrock format
            choice = response.choices[0]
            message = choice.message

            # Build content blocks
            content_blocks = []
            if message.content:
                content_blocks.append({"text": message.content})

            if message.tool_calls:
                for tool_call in message.tool_calls:
                    content_blocks.append({
                        "toolUse": {
                            "toolUseId": tool_call.id,
                            "name": tool_call.function.name,
                            "input": json.loads(tool_call.function.arguments)
                        }
                    })

            # Map finish_reason to Bedrock stopReason
            stop_reason_map = {
                "stop": "end_turn",
                "tool_calls": "tool_use",
                "length": "max_tokens",
            }
            stop_reason = stop_reason_map.get(choice.finish_reason, "end_turn")

            return {
                "output": {
                    "message": {
                        "role": "assistant",
                        "content": content_blocks
                    }
                },
                "stopReason": stop_reason
            }
        except Exception as e:
            logger.error(f"OpenAI API call failed: {type(e).__name__}: {str(e)}")
            logger.error(f"Base URL: {OPENAI_BASE_URL}, Model: {self.model_id}")
            raise


def get_llm_client() -> LLMClient:
    """Get the configured LLM client."""
    return LLMClient()
