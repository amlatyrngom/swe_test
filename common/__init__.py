import boto3.exceptions
import dotenv
import boto3
from botocore.config import Config
import openai
import os
import tiktoken
from enum import Enum

dotenv.load_dotenv()
# Configure the Bedrock client
bedrock_config = Config(
    retries={
        "max_attempts": 1,
    }
)
bedrock_client = boto3.client("bedrock-runtime", region_name="us-east-1", config=bedrock_config)
# TODO: Check if max_retries should be 0 or 1 to get one call.
openai_client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"), max_retries=0)


class LLMType(Enum):
    GPT4 = "gpt4"
    GPT4O = "gpt4o"
    CLAUDE3 = "claude3"
    @staticmethod
    def from_string(s):
        if s == "gpt4":
            return LLMType.GPT4
        if s == "gpt4o":
            return LLMType.GPT4O
        if s == "claude3":
            return LLMType.CLAUDE3
        raise ValueError(f"Unknown LLM type {s}")


class TokenLimitException(Exception):
    def __init__(self, message):
        super().__init__(message)

class RateLimitException(Exception):
    def __init__(self, message):
        super().__init__(message)


def compute_num_tokens(prompt: str):
    encoder = tiktoken.encoding_for_model("gpt-4o")
    tokens = encoder.encode(prompt)
    return len(tokens)

def check_token_limit(system_msg: str, prompt: str, llm_type: LLMType):
    """Check if the prompt exceeds the token limit of the LLM."""

def call_llm(prompt: str, llm_type: LLMType, verbose=False):
    """Call the LLM with the given prompt."""
    if verbose:
        print(f"Calling LLM {llm_type.value} with prompt: {bcolors.BOLD}{bcolors.OKGREEN}{prompt}{bcolors.ENDC}{bcolors.ENDC}")
        print(f"Prompt length: {len(prompt)}")
    system_msg = "You are a programmer trying to fix Github issues. Be sure to format your responses correctly and to only include the necessary changes."
    length = compute_num_tokens(system_msg) + compute_num_tokens(prompt)
    if llm_type == LLMType.GPT4O and length > 128000:
        raise TokenLimitException(f"Token limit exceeded for {llm_type.value}: {length}")
    if llm_type == LLMType.CLAUDE3 and length > 200000:
        raise TokenLimitException(f"Token limit exceeded for {llm_type.value}: {length}")
    if verbose:
        print(f"Number of tokens (tiktoken): {length}")
    check_token_limit(system_msg, prompt, llm_type)
    response = None
    error = None
    if llm_type == LLMType.GPT4 or llm_type == LLMType.GPT4O:
        model = "gpt-4-turbo" if llm_type == LLMType.GPT4 else "gpt-4o"
        try:
            response = openai_client.chat.completions.create(
                model=model,
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
    if llm_type == LLMType.CLAUDE3:
        try:
            response = bedrock_client.converse(
                modelId="anthropic.claude-3-5-sonnet-20240620-v1:0",
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
                if len(prompt) < 75000:
                    # Treat as a rate limit error
                    error = RateLimitException(f"Rate Limit Error (Bedrock): {e}")
                else:
                    # Treat as token limit error
                    error = TokenLimitException(f"Token Limit Error (Bedrock): {e}")
    if error is not None:
        if verbose:
            print(f"{bcolors.FAIL}Error calling LLM:\n{error}{bcolors.ENDC}")
        raise error
    else:
        if verbose:
            print(f"LLM Response:\n{bcolors.BOLD}{bcolors.OKBLUE}{response}{bcolors.ENDC}{bcolors.ENDC}")
        return response


class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
