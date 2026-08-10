import os, subprocess, locale
from pathlib import Path
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

WORKDIR = Path.cwd()
client = Anthropic(base_url=os.getenv("YOUR_BASE_URL"), api_key=os.getenv("YOUR_API_KEY"))
MODEL = os.getenv("YOUR_MODEL_ID")

SYSTEM = f"You are a coding agent at {WORKDIR}. Use tools to solve tasks. Act, don't explain."

# ===========================================================
#  FROM s01 (unchanged)
# ===========================================================

def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    except (FileNotFoundError, OSError) as e:
        return f"Error: {e}"

# ===========================================================
#  NEW in s02: 4 个新工具
# ===========================================================

def safe_path(p: str) -> Path:
    """
    路径安全检查函数：防止工具 (read/write/edit) 访问工作目录之外的文件。
    """
    # 1. 把传入路径拼到工作目录下并解析
    path = (WORKDIR / p).resolve()

    # 2. 检查最终路径是否仍在工作目录内
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")

    # 3. 安全则返回 Path 对象
    return path

def run_read(path: str, limit: int | None = None) -> str:
    """
    read_file 工具的处理函数：收到 LLM 的调用请求后，将文件内容读出来并格式化返回。
    
    Parameters:
        path: 目标文件路径（必填）
        limit: 可选，最多返回多少行；不传则为 None。
        
    Returns:
        str: 返回目标文件的内容
    """
    try: 
        # 1. 路径安全校验后读取文件内容，并按行切分
        lines = safe_path(path).read_text().splitlines()

        # 2. 按行截断文件内容
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]

        # 3. 将切分后的文件内容拼接回去
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"

def run_write(path: str, content: str) -> str:
    """
    write_file 工具的处理函数：把 LLM 生成的内容写入指定文件（自动创建目录、覆盖写入）。
    
    Parameters:
        path: 目标文件路径（必填）
        content: 要写入的内容（必填）
        
    Returns:
        str: 返回写入的字节数，可供 LLM 进行自我核对
    """
    try: 
        # 1. 路径安全校验
        file_path = safe_path(path)

        # 2. 若父目录不存在，会自动创建父目录
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # 3. 执行写入操作
        file_path.write_text(content)

        # 4. 返回写入的字节数
        return f"wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"

def run_edit(path: str, old_text: str, new_text: str) -> str:
    """
    edit_file 工具的处理函数：在目标文件中定位一段精确文本，再替换为新的文本（只替换第一次出现）
    
    Parameters:
        path: 目标文件路径（必填）
        old_text: 要替换的旧文本（必填；必须原样匹配，包括空格、换行、缩进）
        new_text: 替换成的新文本（必填）
    
    Returns: 
        str: 
    """
    try: 
        # 1. 路径安全校验
        file_path = safe_path(path)

        # 2. 全文读取目标文件
        text = file_path.read_text()

        # 3. in 检查旧文本是否存在，若不存在直接返回错误
        if old_text not in text:
            return f"Error: text not found in {path}"

        # 4. 将 replace 替换结果写回文件（统一写 UTF-8）
        file_path.write_text(text.replace(old_text, new_text, 1))

        # 5. 反馈成功编辑的友好提示
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"

def run_glob(pattern: str) -> str:
    """
    glob 工具的处理函数：按通配符模式在工作区内查找文件名，把匹配结果逐行返回给模型。
    
    Parameters: 
        pattern: 待匹配的通配符串
        
    Returns:
        str: 匹配成功则逐行返回匹配结果，失败则返回 (no matches) 的友好提示
    """
    import glob as g
    try: 
        # 1. 创建空列表用于接收匹配结果
        results = []

        # 2. 调用标准库的 glob 模块，从工作目录开始匹配文件
        for match in g.glob(pattern, root_dir=WORKDIR):

            # 3. 路径安全校验，越界自动跳过
            if (WORKDIR / match).resolve().is_relative_to(WORKDIR):
                results.append(match)

        # 4. 逐行返回匹配结果，如果无匹配则返回 (no matches) 的友好提示
        return "\n".join(results) if results else "(no matches)"
    except Exception as e:
        return f"Error: {e}"

# ===========================================================
#  NEW in s02: 工具定义（扩展至 5 个）
# ===========================================================

TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to a file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in a file once.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
    {"name": "glob", "description": "Find files matching a glob pattern.",
     "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]}},
]

# ===========================================================
#  NEW in s02: 工具分发映射（s01 是硬编码 run_bash，现在改为查表）
# ===========================================================
TOOL_HANDLERS = {
    "bash": run_bash, "read_file": run_read, "write_file": run_write,
    "edit_file": run_edit, "glob": run_glob,
}

# ===========================================================
#  agent_loop — 与 s01 结构完全一致，只改了工具执行那部分
#  s01: output = run_bash(block.input["command"])
#  s02: output = TOOL_HANDLERS[block.name](**block.input)
# ===========================================================
def agent_loop(messages: list):
    """
    agent 主循环：反复调用模型，直到模型不再请求工具（给出最终答案）。

    messages 是完整的对话历史，每次循环都会不断追加新的消息，
    保证模型能看到"它说过什么、工具返回了什么"，从而进行多轮推理。
    """
    while True:
        # ── 第 1 步：调用模型 ──────────────────────────────────────────────
        # 把完整历史 + 工具清单发给模型，让模型决定：要么直接回答，
        # 要么请求调用某个工具（停止原因是 tool_use）。
        response = client.messages.create(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=TOOLS, max_tokens=8000,
        )
        # ── 第 2 步：把模型的回复存进历史 ───────────────────────────────────
        # 回复可能含多个内容块（文本 / 工具调用请求）。
        # 必须存进历史，否则后续调用模型时它"忘了"自己说过什么。
        messages.append({"role": "assistant", "content": response.content})

        # ── 第 3 步：判断是否结束 ──────────────────────────────────────────
        # stop_reason == "tool_use" 表示模型想调用工具，需要继续循环；
        # 否则（end_turn / max_tokens 等）说明模型给出了最终答复，直接返回。
        if response.stop_reason != "tool_use":
            return

        # ── 第 4 步：执行模型请求的所有工具调用 ─────────────────────────────
        # 一次回复里可能有多个工具调用（比如先 glob 再 read），逐个执行。
        results = []
        for block in response.content:
            if block.type == "tool_use":
                # 打印工具名（黄色），便于人观察 agent 在做什么
                print(f"\033[33m> {block.name}\033[0m")
                # 查表：工具名 → 处理函数（如 read_file → run_read）
                handler = TOOL_HANDLERS.get(block.name)
                # **block.input 把参数 dict 解包成关键字参数，自动适配任意工具；
                # 找不到处理函数时（理论上不该发生）兜底返回提示文本。
                output = handler(**block.input) if handler else f"Unknown: {block.name}"
                # 打印执行结果前 200 字符，便于人观察
                print(str(output)[:200])
                # 收集结果：tool_result 消息必须携带对应的 tool_use_id，
                # 模型靠这个 id 把"结果"和"它发起的调用"关联起来。
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})

        # ── 第 5 步：把工具结果回传给模型 ───────────────────────────────────
        # 以 user 角色消息形式发给模型，然后回到循环开头，
        # 模型看到结果后继续推理（可能再调用工具，也可能给出最终答案）。
        messages.append({"role": "user", "content": results})
if __name__ == "__main__":
    print("s02: Tool Use — 在 s01 基础上加了 4 个工具")
    print("输入问题，回车发送。输入 q 退出。\n")
    history = []
    while True:
        try:
            query = input("\033[36ms02 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        agent_loop(history)
        for block in history[-1]["content"]:
            if getattr(block, "type", None) == "text":
                print(block.text)
        print()