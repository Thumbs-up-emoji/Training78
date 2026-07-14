import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI
import os
import json
from datetime import datetime

load_dotenv()
client = OpenAI()

CHAT_FOLDER="chats"
PIN_FILE = os.path.join(CHAT_FOLDER, "pins.json")
os.makedirs(CHAT_FOLDER, exist_ok=True)

def load_chat(chat_name):
    filepath = os.path.join(CHAT_FOLDER, f"{chat_name}")
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)

def save_chat(chat_name, messages):
    filepath = os.path.join(CHAT_FOLDER, f"{chat_name}")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(messages, f, indent=4)

def load_pins():
    if not os.path.exists(PIN_FILE):
        return set()

    with open(PIN_FILE, "r", encoding="utf-8") as f:
        try:
            return set(json.load(f))
        except json.JSONDecodeError:
            return set()

def save_pins(pinned_chats):
    with open(PIN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(pinned_chats)), f, indent=4)
    
st.sidebar.title("Chat History")
chat_files = sorted(
    [
        filename
        for filename in os.listdir(CHAT_FOLDER)
        if filename.endswith(".json") and filename != "pins.json"
    ],
    reverse=True,
)
pinned_chats = load_pins()

ordered_chat_files = [f for f in chat_files if f in pinned_chats] + [
    f for f in chat_files if f not in pinned_chats
]

if "chat_name" not in st.session_state or "messages" not in st.session_state:
    if ordered_chat_files:
        # Reuse an existing chat on rerun so selection state stays stable.
        st.session_state.chat_name = ordered_chat_files[0]
        st.session_state.messages = load_chat(st.session_state.chat_name)
    else:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        chat_name = f"Chat_{timestamp}.json"
        st.session_state.chat_name = chat_name
        st.session_state.messages = [{"role": "system", "content": "You are a helpful assistant."}]
        save_chat(chat_name, st.session_state.messages)
        st.rerun()

if st.sidebar.button("New Chat"):
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    chat_name = f"Chat_{timestamp}.json"
    st.session_state.chat_name = chat_name
    st.session_state.messages = [{"role": "system", "content": "You are a helpful assistant."}]
    save_chat(chat_name, st.session_state.messages)
    st.rerun()

st.sidebar.markdown("### Previous Chats")
chat_list_container = st.sidebar.container(height=380)

if not ordered_chat_files:
    chat_list_container.caption("No previous chats yet.")

for chat_file in ordered_chat_files:
    is_current_chat = st.session_state.get("chat_name") == chat_file
    select_col, pin_col = chat_list_container.columns([0.8, 0.2])

    chat_display_name = chat_file.replace(".json", "")

    if select_col.button(
        chat_display_name,
        key=f"select_{chat_file}",
        use_container_width=True,
        type="primary" if is_current_chat else "secondary",
    ):
        if (
            "chat_name" not in st.session_state
            or st.session_state.chat_name != chat_file
        ):
            st.session_state.chat_name = chat_file
            st.session_state.messages = load_chat(chat_file)
            st.rerun()

    pin_icon = "📌" if chat_file in pinned_chats else "📍"
    if pin_col.button(pin_icon, key=f"pin_{chat_file}", use_container_width=True):
        if chat_file in pinned_chats:
            pinned_chats.remove(chat_file)
        else:
            pinned_chats.add(chat_file)
        save_pins(pinned_chats)
        st.rerun()

st.title("Chatbot")

for msg in st.session_state.messages:
    if msg["role"] == "system":
        continue
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

prompt = st.chat_input("Ask away!")

if prompt:
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.spinner("Assistant is typing..."):
        response = client.responses.create(
            model="gpt-4o-mini",
            input=st.session_state.messages
        )

        answer = response.output_text
        st.chat_message("assistant").markdown(answer)
        st.session_state.messages.append({"role": "assistant", "content": answer})
        save_chat(st.session_state.chat_name, st.session_state.messages)