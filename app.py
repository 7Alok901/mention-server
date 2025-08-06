from flask import Flask, render_template, request, jsonify, send_file
import requests
import os
import time
import random
import threading
import json
import uuid
from datetime import datetime, timedelta
from requests.exceptions import RequestException
from werkzeug.utils import secure_filename
import logging

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-change-this')
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('logs', exist_ok=True)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Random User-Agent List for better request handling
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Windows NT 6.1; WOW64; rv:61.0) Gecko/20100101 Firefox/61.0',
    'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:64.0) Gecko/20100101 Firefox/64.0'
]

# Global variables to track automation status with task management
automation_status = {
    'running': False,
    'current_comment': 0,
    'total_comments': 0,
    'current_token': '',
    'current_post': '',
    'task_id': None,
    'start_time': None,
    'logs': []
}

# Dictionary to store active tasks
active_tasks = {}

class CommentAutomation:
    def __init__(self):
        self.active_task_id = None
        
    def log_message(self, message, level='info', task_id=None):
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = {
            'timestamp': timestamp,
            'message': message,
            'level': level,
            'task_id': task_id or self.active_task_id
        }
        automation_status['logs'].append(log_entry)

        if len(automation_status['logs']) > 200:
            automation_status['logs'] = automation_status['logs'][-200:]

        with open('logs/app.log', 'a', encoding='utf-8') as f:
            f.write(f"{timestamp} - {level.upper()} - Task:{task_id or self.active_task_id}: {message}\n")

    def generate_task_id(self):
        return str(uuid.uuid4())[:8]

    def validate_token(self, token, page_id=None, token_type='auto'):
        """
        Validate token - supports both user and page tokens
        token_type: 'user', 'page', or 'auto' (auto-detect)
        """
        try:
            headers = {'User-Agent': random.choice(USER_AGENTS)}
            
            if token_type == 'page' or (token_type == 'auto' and page_id):
                # Try page token validation first
                if page_id:
                    response = requests.get(
                        f'https://graph.facebook.com/v18.0/{page_id}',
                        params={'access_token': token},
                        headers=headers,
                        timeout=10
                    )
                else:
                    # Try to get page info from token
                    response = requests.get(
                        f'https://graph.facebook.com/v18.0/me',
                        params={'access_token': token},
                        headers=headers,
                        timeout=10
                    )
                
                if response.status_code == 200:
                    data = response.json()
                    return True, data.get("name", "Page Token"), 'page'
                    
            if token_type == 'user' or token_type == 'auto':
                # Try user token validation
                response = requests.get(
                    f'https://graph.facebook.com/v18.0/me',
                    params={'access_token': token},
                    headers=headers,
                    timeout=10
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return True, data.get("name", "User Token"), 'user'
            
            # If both fail, return error
            error_data = response.json() if response else {}
            error_msg = error_data.get("error", {}).get("message", "Invalid token")
            return False, error_msg, None
            
        except RequestException as e:
            self.log_message(f"Error validating token: {e}", 'error')
            return False, str(e), None

    def check_token_permissions(self, token):
        """Check what permissions a token has"""
        try:
            headers = {'User-Agent': random.choice(USER_AGENTS)}
            response = requests.get(
                "https://graph.facebook.com/v18.0/me/permissions",
                params={"access_token": token},
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                permissions = response.json().get("data", [])
                granted_permissions = [p["permission"] for p in permissions if p["status"] == "granted"]
                return granted_permissions
            else:
                return []
        except Exception as e:
            self.log_message(f"Error checking permissions: {e}", 'error')
            return []

    def get_valid_tokens(self, tokens, page_id=None, token_type='auto'):
        valid_tokens = []
        for i, token in enumerate(tokens, 1):
            token = token.strip()
            is_valid, name_or_error, detected_type = self.validate_token(token, page_id, token_type)
            if is_valid:
                # Check permissions for page tokens
                permissions = []
                if detected_type == 'page':
                    permissions = self.check_token_permissions(token)
                    required_perms = ['pages_manage_posts', 'pages_read_engagement']
                    missing_perms = [p for p in required_perms if p not in permissions]
                    if missing_perms:
                        self.log_message(f"Token #{i} missing permissions: {missing_perms}", 'warning')
                
                valid_tokens.append({
                    'index': i, 
                    'token': token, 
                    'name': name_or_error,
                    'type': detected_type,
                    'permissions': permissions
                })
                self.log_message(f"Valid {detected_type} token found: {name_or_error}")
            else:
                self.log_message(f"Invalid token #{i}: {name_or_error}", 'warning')
        return valid_tokens

    def post_comment(self, post_id, comment, token_info, mention_id=None, mention_name=None, page_id=None):
        try:
            formatted_comment = f"@[{mention_id}:{mention_name}] {comment}" if mention_id and mention_name else comment
            
            headers = {'User-Agent': random.choice(USER_AGENTS)}
            
            # Use API version for better compatibility
            url = f'https://graph.facebook.com/v18.0/{post_id}/comments/'
            
            data = {
                'message': formatted_comment, 
                'access_token': token_info['token']
            }
            
            # If it's a page token and we have a page_id, specify the page
            if token_info.get('type') == 'page' and page_id:
                data['from'] = page_id
            
            response = requests.post(url, data=data, headers=headers, timeout=15)
            response_data = response.json()
            
            if response.status_code == 200 and 'id' in response_data:
                self.log_message(f"Comment posted successfully by {token_info['name']} ({token_info.get('type', 'unknown')} token)")
                return True, None
            else:
                error_info = response_data.get("error", {})
                error_msg = error_info.get("message", "Unknown error")
                error_code = error_info.get("code", "")
                
                full_error = f"{error_msg} (Code: {error_code})" if error_code else error_msg
                self.log_message(f"Failed to post comment: {full_error}", 'error')
                
                # Return error type for better handling
                if any(keyword in error_msg.lower() for keyword in ["expired", "invalid", "session"]):
                    return False, "invalid_token"
                elif "rate limit" in error_msg.lower():
                    return False, "rate_limit"
                elif "permissions" in error_msg.lower():
                    return False, "permissions"
                elif "spam" in error_msg.lower():
                    return False, "spam"
                else:
                    return False, "other"
                    
        except RequestException as e:
            self.log_message(f"Request error: {e}", 'error')
            return False, "network_error"

    def is_task_stopped(self, task_id):
        return task_id not in active_tasks or active_tasks[task_id].get('stop_flag', False)

    def run_automation(self, task_id, tokens, comments, post_ids, delay, mention_id=None, mention_name=None, page_id=None, token_type='auto'):
        self.active_task_id = task_id
        automation_status.update({
            'running': True,
            'task_id': task_id,
            'start_time': datetime.now().isoformat(),
            'current_comment': 0
        })

        self.log_message(f"Starting infinite comment automation with Task ID: {task_id}")

        valid_tokens = self.get_valid_tokens(tokens, page_id, token_type)
        if not valid_tokens:
            self.log_message("No valid tokens found", 'error')
            automation_status['running'] = False
            active_tasks.pop(task_id, None)
            return

        # Initialize token tracking for round-robin and temporary failures
        token_status = {}
        for token in valid_tokens:
            token_status[token['index']] = {
                'token': token,
                'status': 'active',
                'consecutive_failures': 0,
                'last_failure_time': None,
                'cooldown_until': None,
                'total_comments': 0
            }

        comment_count = 0
        token_index = 0
        cycle_count = 0

        def get_next_available_token():
            """Get next available token using round-robin, skipping temporarily unavailable ones"""
            nonlocal token_index
            attempts = 0
            current_time = datetime.now()
            
            while attempts < len(token_status):
                current_idx = list(token_status.keys())[token_index % len(token_status)]
                token_info = token_status[current_idx]
                
                # Check if token is in cooldown
                if token_info['cooldown_until'] and current_time < token_info['cooldown_until']:
                    remaining_cooldown = (token_info['cooldown_until'] - current_time).seconds
                    self.log_message(f"Token {token_info['token']['name']} in cooldown for {remaining_cooldown}s, skipping...")
                    token_index += 1
                    attempts += 1
                    continue
                
                # Check if token is permanently disabled
                if token_info['status'] == 'disabled':
                    self.log_message(f"Token {token_info['token']['name']} is disabled, skipping...")
                    token_index += 1
                    attempts += 1
                    continue
                
                # Reset cooldown if expired
                if token_info['cooldown_until'] and current_time >= token_info['cooldown_until']:
                    token_info['cooldown_until'] = None
                    token_info['consecutive_failures'] = 0
                    token_info['status'] = 'active'
                    self.log_message(f"Token {token_info['token']['name']} cooldown expired, reactivating...")
                
                return current_idx, token_info['token']
            
            return None, None

        def handle_token_failure(token_idx, error_type):
            """Handle token failure and set appropriate cooldown"""
            token_info = token_status[token_idx]
            token_info['consecutive_failures'] += 1
            token_info['last_failure_time'] = datetime.now()
            
            if error_type == "invalid_token":
                # Permanently disable invalid tokens
                token_info['status'] = 'disabled'
                self.log_message(f"Token {token_info['token']['name']} marked as disabled (invalid)", 'warning')
                return True  # Token should be removed from rotation
                
            elif error_type == "rate_limit":
                # Set cooldown for rate limited tokens
                cooldown_minutes = min(token_info['consecutive_failures'] * 10, 60)  # Max 1 hour
                token_info['cooldown_until'] = datetime.now() + timedelta(minutes=cooldown_minutes)
                token_info['status'] = 'rate_limited'
                self.log_message(f"Token {token_info['token']['name']} rate limited, cooldown: {cooldown_minutes}min", 'warning')
                return False
                
            elif error_type == "spam":
                # Set longer cooldown for spam detection
                cooldown_minutes = min(token_info['consecutive_failures'] * 20, 120)  # Max 2 hours
                token_info['cooldown_until'] = datetime.now() + timedelta(minutes=cooldown_minutes)
                token_info['status'] = 'spam_detected'
                self.log_message(f"Token {token_info['token']['name']} spam detected, cooldown: {cooldown_minutes}min", 'warning')
                return False
                
            elif error_type == "permissions":
                # Temporarily disable for permission errors
                cooldown_minutes = 30
                token_info['cooldown_until'] = datetime.now() + timedelta(minutes=cooldown_minutes)
                token_info['status'] = 'permission_error'
                self.log_message(f"Token {token_info['token']['name']} permission error, cooldown: {cooldown_minutes}min", 'warning')
                return False
            
            else:
                # General error - short cooldown
                cooldown_minutes = min(token_info['consecutive_failures'] * 5, 30)  # Max 30 min
                token_info['cooldown_until'] = datetime.now() + timedelta(minutes=cooldown_minutes)
                token_info['status'] = 'temporary_error'
                self.log_message(f"Token {token_info['token']['name']} temporary error, cooldown: {cooldown_minutes}min", 'warning')
                return False

        try:
            while task_id in active_tasks and not self.is_task_stopped(task_id):
                cycle_count += 1
                self.log_message(f"Starting cycle #{cycle_count}")

                for comment in comments:
                    if self.is_task_stopped(task_id):
                        break

                    for post_id in post_ids:
                        if self.is_task_stopped(task_id):
                            break

                        # Get next available token
                        current_token_idx, current_token = get_next_available_token()
                        
                        if current_token is None:
                            self.log_message("No available tokens at the moment. Waiting 60 seconds...", 'warning')
                            for _ in range(60):
                                if self.is_task_stopped(task_id):
                                    break
                                time.sleep(1)
                            continue

                        automation_status.update({
                            'current_token': current_token['name'],
                            'current_post': post_id,
                            'current_comment': comment_count + 1
                        })

                        self.log_message(f"Cycle {cycle_count} - Comment #{comment_count + 1}: '{comment}' to post {post_id} using {current_token['name']}")

                        success, error_type = self.post_comment(post_id, comment, current_token, mention_id, mention_name, page_id)
                        
                        if success:
                            comment_count += 1
                            token_status[current_token_idx]['total_comments'] += 1
                            token_status[current_token_idx]['consecutive_failures'] = 0  # Reset failure count
                            token_status[current_token_idx]['status'] = 'active'
                            active_tasks[task_id]['comments_posted'] = comment_count
                            
                            # Move to next token in round-robin
                            token_index += 1
                            
                        else:
                            # Handle token failure
                            should_remove = handle_token_failure(current_token_idx, error_type)
                            
                            if should_remove:
                                # Remove permanently failed tokens
                                del token_status[current_token_idx]
                                if not token_status:
                                    self.log_message("No valid tokens remaining. Stopping automation.", 'error')
                                    break
                                # Don't increment token_index as we removed a token
                            else:
                                # Move to next token for temporary failures
                                token_index += 1
                            
                            # For rate limits, wait a bit before continuing
                            if error_type == "rate_limit":
                                self.log_message("Rate limit detected. Waiting 2 minutes before continuing...", 'warning')
                                for _ in range(120):
                                    if self.is_task_stopped(task_id):
                                        break
                                    time.sleep(1)

                        # Check if any tokens are available
                        active_tokens = [t for t in token_status.values() if t['status'] != 'disabled']
                        if not active_tokens:
                            self.log_message("No active tokens remaining. Stopping automation.", 'error')
                            break

                        # Random delay between comments
                        sleep_time = random.randint(delay, delay + 30)
                        self.log_message(f"Waiting {sleep_time} seconds before next comment...")

                        for _ in range(sleep_time):
                            if self.is_task_stopped(task_id):
                                break
                            time.sleep(1)

                # Check if we should continue
                active_tokens = [t for t in token_status.values() if t['status'] != 'disabled']
                if not active_tokens:
                    self.log_message("No active tokens remaining. Stopping automation.", 'error')
                    break
                    
                if not self.is_task_stopped(task_id):
                    # Log token status summary
                    status_summary = {}
                    for token_info in token_status.values():
                        status = token_info['status']
                        status_summary[status] = status_summary.get(status, 0) + 1
                    
                    self.log_message(f"Cycle {cycle_count} completed. Token status: {status_summary}")
                    self.log_message(f"Starting next cycle in 60 seconds...")
                    
                    for _ in range(60):
                        if self.is_task_stopped(task_id):
                            break
                        time.sleep(1)

        except Exception as e:
            self.log_message(f"Automation error: {e}", 'error')

        finally:
            automation_status['running'] = False
            automation_status['task_id'] = None
            if task_id in active_tasks:
                active_tasks[task_id]['status'] = 'completed'
                active_tasks[task_id]['end_time'] = datetime.now().isoformat()
            
            # Log final token statistics
            final_stats = {}
            for token_info in token_status.values():
                final_stats[token_info['token']['name']] = {
                    'total_comments': token_info['total_comments'],
                    'final_status': token_info['status']
                }
            
            self.log_message(f"Automation with Task ID {task_id} completed/stopped. Total comments posted: {comment_count}")
            self.log_message(f"Final token statistics: {final_stats}")

# Initialize automation instance
automation = CommentAutomation()

# ===== FLASK ROUTES =====

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_files():
    try:
        uploaded_files = {}
        for file_type in ['tokens', 'comments']:
            if file_type in request.files:
                file = request.files[file_type]
                if file and file.filename:
                    filename = secure_filename(file.filename)
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_type}_{filename}")
                    file.save(file_path)
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = [line.strip() for line in f.readlines() if line.strip()]
                    uploaded_files[file_type] = content
                    os.remove(file_path)
        return jsonify({'success': True, 'files': uploaded_files})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/start_automation', methods=['POST'])
def start_automation():
    try:
        if automation_status['running']:
            return jsonify({'success': False, 'error': 'Automation is already running'})

        data = request.json
        tokens = data.get('tokens', [])
        comments = data.get('comments', [])
        post_ids = [pid.strip() for pid in data.get('post_ids', '').split(',') if pid.strip()]
        delay = max(60, int(data.get('delay', 60)))
        mention_id = data.get('mention_id', '').strip() or None
        mention_name = data.get('mention_name', '').strip() or None
        page_id = data.get('page_id', '').strip() or None  # Page ID parameter
        token_type = data.get('token_type', 'auto')  # Token type parameter

        if not tokens or not comments or not post_ids:
            return jsonify({'success': False, 'error': 'Missing required data'})

        task_id = automation.generate_task_id()
        active_tasks[task_id] = {
            'id': task_id,
            'status': 'running',
            'start_time': datetime.now().isoformat(),
            'tokens_count': len(tokens),
            'comments_count': len(comments),
            'post_ids_count': len(post_ids),
            'comments_posted': 0,
            'stop_flag': False,
            'page_id': page_id,
            'token_type': token_type
        }

        automation_status['logs'] = []

        thread = threading.Thread(
            target=automation.run_automation,
            args=(task_id, tokens, comments, post_ids, delay, mention_id, mention_name, page_id, token_type)
        )
        thread.daemon = True
        thread.start()

        return jsonify({
            'success': True,
            'message': 'Automation started',
            'task_id': task_id,
            'note': 'This automation will run infinitely until stopped using the task ID'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/validate_tokens', methods=['POST'])
def validate_tokens():
    """Endpoint to validate tokens before starting automation"""
    try:
        data = request.json
        tokens = data.get('tokens', [])
        page_id = data.get('page_id', '').strip() or None
        token_type = data.get('token_type', 'auto')
        
        if not tokens:
            return jsonify({'success': False, 'error': 'No tokens provided'})
        
        valid_tokens = automation.get_valid_tokens(tokens, page_id, token_type)
        
        return jsonify({
            'success': True,
            'total_tokens': len(tokens),
            'valid_tokens': len(valid_tokens),
            'tokens_info': [
                {
                    'index': token['index'],
                    'name': token['name'],
                    'type': token.get('type', 'unknown'),
                    'permissions': token.get('permissions', [])
                }
                for token in valid_tokens
            ]
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/stop_automation', methods=['POST'])
def stop_automation():
    try:
        data = request.json
        task_id = data.get('task_id')
        if not task_id:
            return jsonify({'success': False, 'error': 'Task ID is required'})
        if task_id not in active_tasks:
            return jsonify({'success': False, 'error': 'Invalid or expired task ID'})

        active_tasks[task_id]['stop_flag'] = True
        active_tasks[task_id]['status'] = 'stopping'
        automation.log_message(f"Stop signal sent for Task ID: {task_id}", 'info', task_id)
        return jsonify({'success': True, 'message': f'Stop signal sent for task {task_id}'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/status')
def get_status():
    status_with_tasks = automation_status.copy()
    status_with_tasks['active_tasks'] = active_tasks
    return jsonify(status_with_tasks)

@app.route('/tasks')
def get_tasks():
    return jsonify({'tasks': active_tasks})

@app.route('/task/<task_id>')
def get_task_info(task_id):
    if task_id not in active_tasks:
        return jsonify({'error': 'Task not found'}), 404
    return jsonify({'task': active_tasks[task_id]})

@app.route('/token_status/<task_id>')
def get_token_status(task_id):
    """Get current token status for a running task"""
    if task_id not in active_tasks:
        return jsonify({'error': 'Task not found'}), 404
    
    return jsonify({
        'task_id': task_id,
        'status': 'Token status tracking implemented in run_automation method',
        'note': 'Check logs for detailed token status information'
    })

@app.route('/clear_completed_tasks', methods=['POST'])
def clear_completed_tasks():
    global active_tasks
    active_tasks = {k: v for k, v in active_tasks.items() if v['status'] == 'running'}
    return jsonify({'success': True, 'message': 'Completed tasks cleared'})

@app.route('/download_logs')
def download_logs():
    log_file = 'logs/app.log'
    if os.path.exists(log_file):
        return send_file(log_file, as_attachment=True, download_name='automation_logs.txt')
    else:
        return jsonify({'error': 'No log file found'}), 404

@app.route('/health')
def health_check():
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

# ===== APPLICATION STARTUP =====

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
