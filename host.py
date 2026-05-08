#!/usr/bin/env python3
"""Native messaging host for Gemini Local Agent — Protocol v2."""
import sys
import json
import struct
import subprocess
import os
import logging

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


def handle_run_shell(msg):
    command = msg.get('command')
    req_id = msg.get('id', 'unknown')
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
        send_message({
            'id': req_id,
            'status': 'success',
            'output': combined,
            'code': result.returncode,
            'meta': {'duration_ms': 0}
        })
    except subprocess.TimeoutExpired:
        logging.warning(f"[{req_id}] Command timed out")
        send_message({
            'id': req_id,
            'status': 'error',
            'error': 'Command timed out after 30 seconds.'
        })
    except Exception as e:
        logging.error(f"[{req_id}] Subprocess error: {e}")
        send_message({
            'id': req_id,
            'status': 'error',
            'error': f'Subprocess Exception: {str(e)}'
        })


def handle_write_file(msg):
    filepath = os.path.expanduser(msg.get('filepath'))
    content = msg.get('content')
    req_id = msg.get('id', 'unknown')
    logging.info(f"[{req_id}] Writing file: {filepath}")
    try:
        directory = os.path.dirname(filepath)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        send_message({
            'id': req_id,
            'status': 'success',
            'message': f'File {filepath} written successfully.'
        })
    except Exception as e:
        logging.error(f"[{req_id}] File write error: {e}")
        send_message({
            'id': req_id,
            'status': 'error',
            'error': f'File write error: {str(e)}'
        })


def handle_read_file(msg):
    filepath = os.path.expanduser(msg.get('filepath'))
    req_id = msg.get('id', 'unknown')
    logging.info(f"[{req_id}] Reading file: {filepath}")
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            content = truncate_output(content)
            send_message({
                'id': req_id,
                'status': 'success',
                'output': content
            })
        else:
            send_message({
                'id': req_id,
                'status': 'error',
                'error': f'File not found: {filepath}'
            })
    except Exception as e:
        logging.error(f"[{req_id}] File read error: {e}")
        send_message({
            'id': req_id,
            'status': 'error',
            'error': f'File read error: {str(e)}'
        })


def handle_list_files(msg):
    filepath = os.path.expanduser(msg.get('filepath'))
    req_id = msg.get('id', 'unknown')
    logging.info(f"[{req_id}] Listing files: {filepath}")
    try:
        if os.path.isdir(filepath):
            entries = os.listdir(filepath)
            output = '\n'.join(entries)
        elif os.path.exists(filepath):
            output = f"{filepath} is a file, not a directory."
        else:
            output = f"Path not found: {filepath}"
        send_message({
            'id': req_id,
            'status': 'success',
            'output': output
        })
    except Exception as e:
        send_message({
            'id': req_id,
            'status': 'error',
            'error': f'List error: {str(e)}'
        })


logging.info("Gemini Host v2 Started")

while True:
    try:
        msg = get_message()
        action = msg.get('action')
        req_id = msg.get('id', 'unknown')

        if action == 'run_shell':
            handle_run_shell(msg)
        elif action == 'write_file':
            handle_write_file(msg)
        elif action == 'read_file':
            handle_read_file(msg)
        elif action == 'list_files':
            handle_list_files(msg)
        else:
            logging.warning(f"[{req_id}] Unknown action: {action}")
            send_message({
                'id': req_id,
                'status': 'error',
                'error': f'Unknown action: {action}'
            })
    except Exception as fatal_error:
        logging.critical(f"Fatal error in main loop: {fatal_error}")
        try:
            send_message({
                'id': msg.get('id', 'unknown') if 'msg' in dir() else 'unknown',
                'status': 'fatal_error',
                'error': str(fatal_error)
            })
        except Exception:
            pass
        sys.exit(1)
