#!/usr/bin/env python3
"""Native messaging host for Gemini Local Agent — Protocol v2."""
import sys
import json
import struct
import subprocess
import os
import logging
import time
import tempfile

logging.basicConfig(
    filename='/tmp/gemini_host.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

MAX_OUTPUT_SIZE = 1024 * 1024  # 1MB


def get_message():
    try:
        raw_length = sys.stdin.buffer.read(4)
        if len(raw_length) == 0:
            logging.info("Input stream closed. Exiting.")
            sys.exit(0)
        message_length = struct.unpack('@I', raw_length)[0]
        message = sys.stdin.buffer.read(message_length).decode('utf-8')
        logging.debug(f"Received message: {message[:200]}...")
        return json.loads(message)
    except Exception as e:
        logging.error(f"Error reading message: {e}")
        sys.exit(1)


def send_message(message_dict):
    try:
        encoded = json.dumps(message_dict).encode('utf-8')
        sys.stdout.buffer.write(struct.pack('@I', len(encoded)))
        sys.stdout.buffer.write(encoded)
        sys.stdout.buffer.flush()
        logging.debug(f"Sent response: {str(message_dict)[:200]}...")
    except Exception as e:
        logging.error(f"Error sending message: {e}")


def truncate_output(text, max_bytes=MAX_OUTPUT_SIZE):
    if text is None:
        text = ""
    encoded = text.encode('utf-8')
    if len(encoded) <= max_bytes:
        return text
    truncated = encoded[:max_bytes].decode('utf-8', errors='ignore')
    return truncated + f"\n\n[Output truncated: exceeded {max_bytes} bytes]"


def respond_success(req_id, meta, output=None, message=None, code=None):
    response = {
        'id': req_id,
        'status': 'success',
        'meta': meta,
    }
    if output is not None:
        response['output'] = output
    if message is not None:
        response['message'] = message
    if code is not None:
        response['code'] = code
    send_message(response)


def respond_error(req_id, meta, error, status='error'):
    send_message({
        'id': req_id,
        'status': status,
        'error': error,
        'meta': meta,
    })


def handle_run_shell(msg):
    command = msg.get('command')
    req_id = msg.get('id', 'unknown')
    start = time.perf_counter()
    logging.info(f"[{req_id}] Executing shell command: {command}")
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30
        )
        output = result.stdout or ""
        error = result.stderr or ""
        combined = output
        if error:
            combined += f"\n--- Standard Error ---\n{error}"
        if not combined.strip():
            combined = f"[Command completed with exit code {result.returncode} and no output]"

        combined = truncate_output(combined)
        duration_ms = round((time.perf_counter() - start) * 1000)
        respond_success(
            req_id,
            {'duration_ms': duration_ms},
            output=combined,
            code=result.returncode
        )
    except subprocess.TimeoutExpired:
        duration_ms = round((time.perf_counter() - start) * 1000)
        logging.warning(f"[{req_id}] Command timed out")
        respond_error(
            req_id,
            {'duration_ms': duration_ms},
            'Command timed out after 30 seconds.'
        )
    except Exception as e:
        duration_ms = round((time.perf_counter() - start) * 1000)
        logging.error(f"[{req_id}] Subprocess error: {e}")
        respond_error(
            req_id,
            {'duration_ms': duration_ms},
            f'Subprocess Exception: {str(e)}'
        )


def handle_write_file(msg):
    filepath = os.path.expanduser(msg.get('filepath'))
    content = msg.get('content')
    req_id = msg.get('id', 'unknown')
    start = time.perf_counter()
    logging.info(f"[{req_id}] Writing file: {filepath}")
    try:
        directory = os.path.dirname(filepath)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        duration_ms = round((time.perf_counter() - start) * 1000)
        respond_success(
            req_id,
            {'duration_ms': duration_ms},
            message=f'File {filepath} written successfully.'
        )
    except Exception as e:
        duration_ms = round((time.perf_counter() - start) * 1000)
        logging.error(f"[{req_id}] File write error: {e}")
        respond_error(
            req_id,
            {'duration_ms': duration_ms},
            f'File write error: {str(e)}'
        )


def handle_read_file(msg):
    filepath = os.path.expanduser(msg.get('filepath'))
    req_id = msg.get('id', 'unknown')
    start = time.perf_counter()
    logging.info(f"[{req_id}] Reading file: {filepath}")
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            content = truncate_output(content)
            duration_ms = round((time.perf_counter() - start) * 1000)
            respond_success(
                req_id,
                {'duration_ms': duration_ms},
                output=content
            )
        else:
            duration_ms = round((time.perf_counter() - start) * 1000)
            respond_error(
                req_id,
                {'duration_ms': duration_ms},
                f'File not found: {filepath}'
            )
    except Exception as e:
        duration_ms = round((time.perf_counter() - start) * 1000)
        logging.error(f"[{req_id}] File read error: {e}")
        respond_error(
            req_id,
            {'duration_ms': duration_ms},
            f'File read error: {str(e)}'
        )


def handle_list_files(msg):
    filepath = os.path.expanduser(msg.get('filepath'))
    req_id = msg.get('id', 'unknown')
    start = time.perf_counter()
    logging.info(f"[{req_id}] Listing files: {filepath}")
    try:
        if os.path.isdir(filepath):
            entries = os.listdir(filepath)
            output = '\n'.join(entries)
        elif os.path.exists(filepath):
            output = f"{filepath} is a file, not a directory."
        else:
            output = f"Path not found: {filepath}"
        duration_ms = round((time.perf_counter() - start) * 1000)
        respond_success(
            req_id,
            {'duration_ms': duration_ms},
            output=output
        )
    except Exception as e:
        duration_ms = round((time.perf_counter() - start) * 1000)
        respond_error(
            req_id,
            {'duration_ms': duration_ms},
            f'List error: {str(e)}'
        )


def handle_git_command(msg, subcommand):
    directory = os.path.expanduser(msg.get('filepath', '.'))
    req_id = msg.get('id', 'unknown')
    start = time.perf_counter()
    logging.info(f"[{req_id}] Git {subcommand} in: {directory}")
    try:
        result = subprocess.run(
            ['git', subcommand],
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=30
        )
        output = result.stdout or ""
        if result.stderr:
            logging.warning(f"[{req_id}] Git {subcommand} stderr: {result.stderr}")
        if not output.strip():
            output = f"[Command completed with exit code {result.returncode} and no output]"
        output = truncate_output(output)
        duration_ms = round((time.perf_counter() - start) * 1000)
        if result.returncode != 0:
            respond_error(
                req_id,
                {'duration_ms': duration_ms},
                output
            )
        else:
            respond_success(
                req_id,
                {'duration_ms': duration_ms},
                output=output
            )
    except subprocess.TimeoutExpired:
        duration_ms = round((time.perf_counter() - start) * 1000)
        logging.warning(f"[{req_id}] Git {subcommand} timed out")
        respond_error(
            req_id,
            {'duration_ms': duration_ms},
            f'Git {subcommand} timed out after 30 seconds.'
        )
    except Exception as e:
        duration_ms = round((time.perf_counter() - start) * 1000)
        logging.error(f"[{req_id}] Git {subcommand} error: {e}")
        respond_error(
            req_id,
            {'duration_ms': duration_ms},
            f'Git {subcommand} error: {str(e)}'
        )


def handle_git_status(msg):
    handle_git_command(msg, 'status')


def handle_git_diff(msg):
    handle_git_command(msg, 'diff')


def handle_run_python(msg):
    req_id = msg.get('id', 'unknown')
    start = time.perf_counter()
    filepath = msg.get('filepath')
    content = msg.get('content')
    logging.info(f"[{req_id}] Running Python code")

    script_path = None
    temp_file = None
    try:
        if content is not None:
            temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8')
            temp_file.write(content)
            temp_file.close()
            script_path = temp_file.name
        elif filepath is not None:
            script_path = os.path.expanduser(filepath)
            if not os.path.exists(script_path):
                duration_ms = round((time.perf_counter() - start) * 1000)
                respond_error(
                    req_id,
                    {'duration_ms': duration_ms},
                    f'File not found: {script_path}'
                )
                return
        else:
            duration_ms = round((time.perf_counter() - start) * 1000)
            respond_error(
                req_id,
                {'duration_ms': duration_ms},
                'Either filepath or content must be provided for run_python.'
            )
            return

        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=30
        )
        output = result.stdout or ""
        if result.stderr:
            output += f"\n--- Standard Error ---\n{result.stderr}"
        if not output.strip():
            output = f"[Command completed with exit code {result.returncode} and no output]"
        output = truncate_output(output)
        duration_ms = round((time.perf_counter() - start) * 1000)
        respond_success(
            req_id,
            {'duration_ms': duration_ms},
            output=output,
            code=result.returncode
        )
    except subprocess.TimeoutExpired:
        duration_ms = round((time.perf_counter() - start) * 1000)
        logging.warning(f"[{req_id}] Python execution timed out")
        respond_error(
            req_id,
            {'duration_ms': duration_ms},
            'Python execution timed out after 30 seconds.'
        )
    except Exception as e:
        duration_ms = round((time.perf_counter() - start) * 1000)
        logging.error(f"[{req_id}] Python execution error: {e}")
        respond_error(
            req_id,
            {'duration_ms': duration_ms},
            f'Python execution error: {str(e)}'
        )
    finally:
        if temp_file is not None:
            try:
                os.unlink(temp_file.name)
            except Exception:
                pass


if __name__ == '__main__':
    logging.info("Gemini Host v2 Started")

    while True:
        try:
            msg = get_message()
            action = msg.get('action')
            req_id = msg.get('id', 'unknown')
            start = time.perf_counter()

            if action == 'run_shell':
                handle_run_shell(msg)
            elif action == 'write_file':
                handle_write_file(msg)
            elif action == 'read_file':
                handle_read_file(msg)
            elif action == 'list_files':
                handle_list_files(msg)
            elif action == 'git_status':
                handle_git_status(msg)
            elif action == 'git_diff':
                handle_git_diff(msg)
            elif action == 'run_python':
                handle_run_python(msg)
            else:
                duration_ms = round((time.perf_counter() - start) * 1000)
                logging.warning(f"[{req_id}] Unknown action: {action}")
                respond_error(
                    req_id,
                    {'duration_ms': duration_ms},
                    f'Unknown action: {action}'
                )
        except Exception as fatal_error:
            logging.critical(f"Fatal error in main loop: {fatal_error}")
            try:
                respond_error(
                    msg.get('id', 'unknown') if 'msg' in dir() else 'unknown',
                    {'duration_ms': 0},
                    str(fatal_error),
                    status='fatal_error'
                )
            except Exception:
                pass
            sys.exit(1)
