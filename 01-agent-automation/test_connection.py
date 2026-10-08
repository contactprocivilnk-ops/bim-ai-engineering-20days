import os
from dotenv import load_dotenv
from google import genai

# Load environment variables from .env file
load_dotenv()

# Retrieve API key
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise ValueError("GEMINI_API_KEY not found in .env file.")

# Initialize the Gemini client
client = genai.Client(api_key=api_key)

# Send a test prompt using the updated model
response = client.models.generate_content(
    model="gemini-3.8-flash",
    contents="Explain in one concise sentence how python can automate Revit workflows.",
)

# Print the response
print("\n--- Connection Successful! ---")
print(response.text)