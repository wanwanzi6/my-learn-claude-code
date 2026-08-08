import os
import subprocess
from anthropic import Anthropic
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv(override=True)

# 创建兼容 Anthropic API 的 LLM 客户端
client = Anthropic(base_url=os.getenv("YOUR_BASE_URL"), api_key=os.getenv("YOUR_API_KEY"))
MODEL = os.environ["YOUR_MODEL_ID"]

# 定义系统提示词
SYSTEM = f"You are a coding agent at {os.getcwd()}. Use bash to solve tasks. Act, don't explain."

# ==================== 工具定义 ====================
TOOLS = [{
    "name": "bash",
    "description": "Run a shell command.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}]

# ==================== 工具执行函数 ====================
def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=os.getcwd(),
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    except (FileNotFoundError, OSError) as e:
        return f"Error: {e}"

def agent_loop(messages: list):
    """
    a while loop: LLM 在循环中持续调用工具，直到 LLM 停止
    """
    while True:
        response = client.messages.create(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=TOOLS, max_tokens=8000,
        )

        # 构建 assistant 消息并添加至消息列表
        messages.append({"role": "assistant", "content": response.content})

        # 如果 LLM 不再调用工具，就结束任务
        if response.stop_reason != "tool_use":
            return

        # 执行工具调用，并收集工具调用结果
        results = []
        for block in response.content:
            if block.type == "tool_use":
                print(f"\033[33m$ {block.input['command']}\033[0m")
                output = run_bash(block.input["command"])
                print(output[:200])
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                })

        # 返回工具调用结果，继续下一轮循环
        messages.append({"role": "user", "content": results})

# ==================== 主函数入口 ====================
if __name__ == "__main__":
    print("s01: Agent Loop")
    print("输入问题，回车发送，输入 q 退出。\n")

    # 创建历史消息列表
    history = []
    while True:
        try:
            query = input("\033[36ms01 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        # 用户输入的问题作为第一条消息
        history.append({"role": "user", "content": query})
        # 启动 Agent Loop
        agent_loop(history)
        # 输出 LLM 最后一轮的文本响应内容
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if getattr(block, "type", None) == "text":
                    print(block.text)
        print()
