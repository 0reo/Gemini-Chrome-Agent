#!/usr/bin/env python3
import sys
import json
import struct
import subprocess
import os
import logging

# Configure logging to help debug the "System Result" empty issue
logging.basicConfig(
    filename='/tmp/gemini_host.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

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

logging.info("Gemini Host Script Started")

while True:
    try:
        msg = get_message()
        action = msg.get('action')
        
        if action == 'run_shell':
            command = msg.get('command')
            logging.info(f"Executing shell command: {command}")
            try:
                # Use shell=True for pipes/redirects. text=True handles decoding automatically.
                result = subprocess.run(
                    command, 
                    shell=True, 
                    capture_output=True, 
                    text=True, 
                    timeout=30 # Add a timeout to prevent hanging the loop
                )
                
                output = result.stdout or ""
                error = result.stderr or ""
                
                combined_output = output
                if error:
                    combined_output += f"\n--- Standard Error ---\n{error}"
                
                if not combined_output.strip():
                    combined_output = f"[Command completed with exit code {result.returncode} and no output]"
                
                send_message({'status': 'success', 'output': combined_output, 'code': result.returncode})
                
            except subprocess.TimeoutExpired:
                logging.warning("Command timed out")
                send_message({'status': 'error', 'error': 'Command timed out after 30 seconds.'})
            except Exception as e:
                logging.error(f"Subprocess error: {e}")
                send_message({'status': 'error', 'error': f'Subprocess Exception: {str(e)}'})
                
        elif action == 'write_file':
            filepath = msg.get('filepath')
            content = msg.get('content')
            logging.info(f"Writing file: {filepath}")
            try:
                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                with open(filepath, 'w') as f:
                    f.write(content)
                send_message({'status': 'success', 'message': f'File {filepath} written successfully.'})
            except Exception as e:
                logging.error(f"File write error: {e}")
                send_message({'status': 'error', 'error': f'File write error: {str(e)}'})
        else:
            logging.warning(f"Unknown action received: {action}")
            send_message({'status': 'error', 'error': f'Unknown action: {action}'})
            
    except Exception as fatal_error:
        logging.critical(f"Fatal error in main loop: {fatal_error}")
        try:
            send_message({'status': 'fatal_error', 'error': str(fatal_error)})
        except:
            pass
        sys.exit(1)