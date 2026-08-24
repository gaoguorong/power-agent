from llm_client import LLMClient


llm_client = LLMClient()
response = llm_client.parse_question("你好")
print(response)
