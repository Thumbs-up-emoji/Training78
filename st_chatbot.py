from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()
client = OpenAI()

messages = [{"role": "system", "content": "You are a helpful assistant."}]

print("Type 'exit' to quit.")

while True:
    user = input("You: \n")
    if user.lower() == "exit":
        print("Exiting the chat. Goodbye!")
        break
    
    messages.append({"role": "user", "content": user})

    response = client.responses.create(
        model="gpt-4o-mini",
        input = messages
    )

    assistant = response.output_text
    print(f"Assistant: {assistant}\n")