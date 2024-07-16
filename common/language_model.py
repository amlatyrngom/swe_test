from .cache import CACHE
from .colors import bcolors
import tomllib
import boto3
import typing as t
from botocore.config import Config
import os
import openai
from enum import Enum
import json
import dotenv

class TokenLimitException(Exception):
    """Exception raised exceeding token limit."""
    pass

class RateLimitException(Exception):
    """Exception raised exceeding rate limit."""
    pass

class LLMType(Enum):
    GPT_4O = "gpt-4o"
    SONNET = "sonnet"

    @staticmethod
    def from_string(s):
        if s in ["gpt-4o", "gpt4o"]:
            return LLMType.GPT_4O
        if s in ["claude3", "sonnet"]:
            return LLMType.SONNET
        raise ValueError(f"Unknown LLM type {s}")

    def is_openai(self):
        return self in [LLMType.GPT_4O]
    
    def is_bedrock(self):
        return self in [LLMType.SONNET]

    def model_id(self) -> str:
        if self == LLMType.GPT_4O:
            return "gpt-4o"
        if self == LLMType.SONNET:
            return "anthropic.claude-3-5-sonnet-20240620-v1:0"
        raise ValueError(f"Unknown LLM type {self}")
    


class LanguageModel:
    def __init__(self):
        """Initialize the language model."""
        self.config = tomllib.load(open("configs/main.toml", "rb"))
        self.verbose = self.config["verbose"]
        self.llm = LLMType.from_string(self.config["llm"])
        self.default_system_msg = self.config["default_system_msg"].strip()
        bedrock_config = Config(
            retries={
                "max_attempts": 1,
            }
        )
        if self.llm.is_openai():
            self.client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"), max_retries=0)
        if self.llm.is_bedrock():
            self.client = boto3.client("bedrock-runtime", region_name="us-east-1", config=bedrock_config)


    def _invoke_openai(self, system_msg: str, prompt: str) -> str:
        """Invoke the LLM using OpenAI."""
        if not self.within_prompt_limits(prompt, system_msg):
            raise TokenLimitException("Token limit exceeded (OpenAI).")
        model_id = self.llm.model_id()
        response, error = None, None
        try:
            response = self.client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0,
            )
            response = response.choices[0].message.content
        except openai.BadRequestError as e:
            error = TokenLimitException(f"Token Limit Error (OpenAI): {e}")
        except openai.RateLimitError as e:
            error = RateLimitException(f"Rate Limit Error (OpenAI): {e}")
        except Exception as e:
            error = e
        return response, error

    def _invoke_bedrock(self, system_msg: str, prompt: str) -> str:
        """Invoke the LLM using Bedrock."""
        if not self.within_prompt_limits(prompt, system_msg):
            raise TokenLimitException("Token limit exceeded (Bedrock).")
        response, error = None, None
        model_id = self.llm.model_id()
        try:
            response = self.client.converse(
                modelId=model_id,
                messages=[
                    {"role": "user", "content": [{"text": prompt}]}
                ],
                system=[
                    {"text": system_msg}
                ],
                inferenceConfig={"temperature": 0.0},
            )
            response = response["output"]["message"]["content"][0]["text"]
        except Exception as e:
            error = e
            if "ThrottlingException" in f"{e}":
                # Treat as a rate limit error
                error = RateLimitException(f"Rate Limit Error (Bedrock): {e}")
        return response, error


    def _embed_openai(self, text: str):
        """Embed text using OpenAI."""
        if not self.within_embedding_limits(text):
            raise TokenLimitException("Embedding token limit exceeded (OpenAI).")
        response, error = None, None
        try:
            response = self.client.embeddings.create(
                input=[text],
                model="text-embedding-3-large",
                dimensions=1024,
            ).data[0].embedding
        except openai.BadRequestError as e:
            error = TokenLimitException(f"Embedding Limit Error (OpenAI): {e}")
        except openai.RateLimitError as e:
            error = RateLimitException(f"Embedding Rate Limit Error (OpenAI): {e}")
        except Exception as e:
            error = e
        return response, error
    
    def _embed_bedrock(self, text: str):
        """Embed text using Bedrock."""
        if not self.within_embedding_limits(text):
            raise TokenLimitException("Embedding token limit exceeded (Bedrock).")
        response, error = None, None
        try:
            body = json.dumps({
                "inputText": text,
                "dimensions": 1024,
                "normalize": True,
            })
            response = self.client.invoke_model(
                body=body,
                modelId="amazon.titan-embed-text-v2:0",
                accept="application/json",
                contentType="application/json",
            )
            response = json.loads(response.get("body").read())
            response = response.get("embedding")
        except Exception as e:
            error = e
            if "ThrottlingException" in f"{e}":
                error = TokenLimitException(f"Embedding Rate Limit Error (Bedrock): {e}")
        return response, error


    def invoke(self, prompt: str, cache_key: t.Optional[str] = None, system_msg: t.Optional[str] = None) -> str:
        """Invoke the LLM."""
        # Default system message
        if system_msg is None:
            system_msg = self.default_system_msg
        # Check cache
        if cache_key is not None:
            cache_prompt = f"{system_msg}____{prompt}"
            cached = CACHE.get_prompt(cache_key, cache_prompt)
            if cached is not None:
                if self.verbose:
                    print(f"{bcolors.OKBLUE}Using cached response for {cache_key}.{bcolors.ENDC}")
                return cached
        if self.verbose:
            print(f"{bcolors.OKGREEN}{bcolors.BOLD}Prompt:\n{prompt}{bcolors.ENDC}")
        # Call LLM
        if self.llm.is_openai():
            response, error = self._invoke_openai(system_msg, prompt)
        elif self.llm.is_bedrock():
            response, error = self._invoke_bedrock(system_msg, prompt)
        # Check for errors.
        if error is not None:
            if self.verbose:
                print(f"{bcolors.FAIL}Error: {error}{bcolors.ENDC}")
            raise error
        # Cache response
        if cache_key is not None:
            cache_prompt = f"{system_msg}____{prompt}"
            CACHE.set_prompt(cache_key, cache_prompt, response)
        # Done.
        if self.verbose:
            print(f"{bcolors.OKBLUE}Response: {response}{bcolors.ENDC}")
        return response


    def embed(self, text: str, cache_key: t.Optional[str] = None) -> t.List[float]:
        """Embed text."""
        # Check cache.
        cached_response = CACHE.get_prompt(cache_key, text)
        if cached_response is not None:
            if self.verbose:
                print(f"{bcolors.OKBLUE}Using cached embedding for {cache_key}{bcolors.ENDC}")
            return cached_response
        if self.verbose:
            print(f"{bcolors.OKGREEN}{bcolors.BOLD}Calling Embedding ({cache_key}):\n{text}{bcolors.ENDC}")
        # Make the call.
        if self.llm.is_openai():
            response, error = self._embed_openai(text)
        elif self.llm.is_bedrock():
            response, error = self._embed_bedrock(text)
        # Check error
        if error is not None:
            if self.verbose:
                print(f"{bcolors.FAIL}Error: {error}{bcolors.ENDC}")
            raise error
        # Cache.
        if cache_key is not None:
            CACHE.set_prompt(cache_key, text, response)
        # Done.
        if self.verbose:
            print(f"{bcolors.OKBLUE}Embedding: {response[:4]}{bcolors.ENDC}")
        return response


    def within_prompt_limits(self, prompt: str, system_msg: t.Optional[str] = None):
        """Check if the prompt is within the limits."""
        # Clause does not support client-side tokenization or limit checking. So I am using a heuristic.
        # This should be a generous enough limit.
        if system_msg is None:
            system_msg = self.default_system_msg
        return len(prompt) + len(system_msg) <= 96_000
    
    def within_embedding_limits(self, text: str):
        """Check if the text is within the embedding limits."""
        # Clause does not support client-side tokenization or limit checking. So I am using a heuristic.
        # This should be a generous enough limit.
        return len(text) <= 5000
    

    def _parse_block(self, output: str, tag: str, lang: str=None):
        """Parse code between <tag attrs> and </tag>"""
        start_tag = f"<{tag}"
        end_tag = f"</{tag}>"
        start = output.find(start_tag)
        end = output.find(end_tag)
        if start == -1 or end == -1:
            return None
        # Parse attributes: attr1=value1 attr2=value2
        attrs_start = start + len(start_tag)
        attrs_end = output.find(">", attrs_start)
        attrs = output[attrs_start:attrs_end]
        attrs = attrs.split(" ")
        attrs = {a.split("=")[0]: a.split("=")[1] for a in attrs if "=" in a}
        # Parse content
        start_block = attrs_end + 1
        end_block = output.find(end_tag, start_block)
        block = output[start_block:end_block]
        if block.startswith("\n"):
            block = block[1:]
        if block.endswith("\n"):
            block = block[:-1]
        # Remove possible surroundings. Keep this order.
        possible_surroundings = ["```json, ```diff, ```py", "```md", "```\n", "\n```"]
        if lang is not None:
            possible_surroundings = [f"```{lang}"] + possible_surroundings
        for surrounding in possible_surroundings:
            block = block.replace(surrounding, "```")
        block = block.replace("```", "")
        return block, attrs

    def parse_standard_response(self, response: str, reason_tag: str="reason", code_tag: str="patch", code_lang: str="diff"):
        """Parse a standard LLM response."""
        reasons = {}
        codes = {}
        attrs = {}
        i = -1
        while True:
            if i == -1:
                # Parse overall explanation/code.
                curr_reason_tag = reason_tag
                curr_code_tag = code_tag
            else:
                # Parse individual explanations/code.
                curr_reason_tag = f"{reason_tag}{i}"
                curr_code_tag = f"{code_tag}{i}"
            res = self._parse_block(response, curr_reason_tag, lang="md")
            if res is not None:
                explanation, attr = res
                reasons[curr_reason_tag] = explanation
                if len(attr) > 0:
                    attrs[curr_reason_tag] = attr
            res = self._parse_block(response, curr_code_tag, lang=code_lang)
            if res is not None:
                codeblock, attr = res
                codes[curr_code_tag] = codeblock
                if len(attr) > 0:
                    attrs[curr_code_tag] = attr
            else:
                if i >= 0:
                    break
            i += 1
        return reasons, codes, attrs


dotenv.load_dotenv()
LANGUAGE_MODEL = LanguageModel()