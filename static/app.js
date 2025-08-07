// Facebook Comment Automation - Frontend JavaScript

class CommentAutomation {
    constructor() {
        this.uploadedFiles = {};
        this.runningTasks = [];
        this.init();
    }

    init() {
        this.bindEvents();
        this.loadRunningTasks();
        setInterval(() => this.loadRunningTasks(), 5000); // Refresh every 5 seconds
    }

    bindEvents() {
        // Form submission
        document.getElementById('taskForm').addEventListener('submit', (e) => {
            e.preventDefault();
            this.handleFormSubmit();
        });

        // File uploads
        document.getElementById('tokenFile').addEventListener('change', (e) => {
            this.handleFileUpload('tokens', e.target.files[0]);
        });

        document.getElementById('commentFile').addEventListener('change', (e) => {
            this.handleFileUpload('comments', e.target.files[0]);
        });

        // Delay mode radio buttons
        document.querySelectorAll('input[name="delayMode"]').forEach(radio => {
            radio.addEventListener('change', this.handleDelayModeChange);
        });

        // Mention checkbox
        document.getElementById('enableMentions').addEventListener('change', (e) => {
            const mentionInputs = document.getElementById('mentionInputs');
            mentionInputs.style.display = e.target.checked ? 'block' : 'none';
        });

        // Stop task button
        document.getElementById('stopTaskBtn').addEventListener('click', () => {
            this.stopTask();
        });

        // Refresh tasks button
        document.getElementById('refreshTasks').addEventListener('click', () => {
            this.loadRunningTasks();
        });

        // Min/Max delay validation
        document.getElementById('minDelay').addEventListener('input', this.validateDelayInputs);
        document.getElementById('maxDelay').addEventListener('input', this.validateDelayInputs);
    }

    handleDelayModeChange() {
        const randomMode = document.getElementById('randomDelay').checked;
        const randomInputs = document.getElementById('randomDelayInputs');
        const accurateInputs = document.getElementById('accurateDelayInputs');
        
        randomInputs.style.display = randomMode ? 'block' : 'none';
        accurateInputs.style.display = randomMode ? 'none' : 'block';
    }

    validateDelayInputs() {
        const minDelay = parseInt(document.getElementById('minDelay').value);
        const maxDelay = parseInt(document.getElementById('maxDelay').value);
        
        if (minDelay >= maxDelay) {
            document.getElementById('maxDelay').value = minDelay + 1;
        }
    }

    async handleFileUpload(type, file) {
        if (!file) return;

        const formData = new FormData();
        formData.append(type, file);

        try {
            this.showLoading(`Uploading ${type} file...`);
            
            const response = await fetch('/upload', {
                method: 'POST',
                body: formData
            });

            const result = await response.json();
            
            if (result.success) {
                this.uploadedFiles[type] = result.files[type];
                this.showAlert(`${type.charAt(0).toUpperCase() + type.slice(1)} file uploaded successfully!`, 'success');
            } else {
                this.showAlert(`Failed to upload ${type} file: ${result.error}`, 'danger');
            }
        } catch (error) {
            this.showAlert(`Error uploading ${type} file: ${error.message}`, 'danger');
        } finally {
            this.hideLoading();
        }
    }

    async handleFormSubmit() {
        if (!this.validateForm()) return;

        const formData = this.collectFormData();
        
        try {
            this.showLoading('Starting task...');
            document.getElementById('startBtn').disabled = true;

            const response = await fetch('/start_task', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(formData)
            });

            const result = await response.json();

            if (result.success) {
                this.showAlert(`Task started successfully! Task ID: ${result.task_id}`, 'success');
                this.resetForm();
                this.loadRunningTasks();
            } else {
                this.showAlert(`Failed to start task: ${result.error}`, 'danger');
            }
        } catch (error) {
            this.showAlert(`Error starting task: ${error.message}`, 'danger');
        } finally {
            this.hideLoading();
            document.getElementById('startBtn').disabled = false;
        }
    }

    validateForm() {
        // Check if files are uploaded
        if (!this.uploadedFiles.tokens) {
            this.showAlert('Please upload a tokens file', 'danger');
            return false;
        }

        if (!this.uploadedFiles.comments) {
            this.showAlert('Please upload a comments file', 'danger');
            return false;
        }

        // Check post ID
        const postId = document.getElementById('postId').value.trim();
        if (!postId) {
            this.showAlert('Please enter a Facebook Post ID', 'danger');
            return false;
        }

        // Validate delay configuration
        const delayMode = document.querySelector('input[name="delayMode"]:checked').value;
        
        if (delayMode === 'random') {
            const minDelay = parseInt(document.getElementById('minDelay').value);
            const maxDelay = parseInt(document.getElementById('maxDelay').value);
            
            if (minDelay < 1 || maxDelay < 1 || minDelay >= maxDelay) {
                this.showAlert('Please enter valid delay values (min < max, both > 0)', 'danger');
                return false;
            }
        } else {
            const delayValues = document.getElementById('delayValues').value.trim();
            if (!delayValues) {
                this.showAlert('Please enter delay values for accurate mode', 'danger');
                return false;
            }

            const values = delayValues.split(',').map(v => parseInt(v.trim()));
            if (values.some(v => isNaN(v) || v < 1)) {
                this.showAlert('Please enter valid delay values (numbers > 0)', 'danger');
                return false;
            }
        }

        // Validate mentions if enabled
        const mentionsEnabled = document.getElementById('enableMentions').checked;
        if (mentionsEnabled) {
            const mentionId = document.getElementById('mentionId').value.trim();
            const mentionName = document.getElementById('mentionName').value.trim();
            
            if (!mentionId || !mentionName) {
                this.showAlert('Please enter both Mention ID and Name', 'danger');
                return false;
            }
        }

        return true;
    }

    collectFormData() {
        const delayMode = document.querySelector('input[name="delayMode"]:checked').value;
        const mentionsEnabled = document.getElementById('enableMentions').checked;

        const formData = {
            token_file: this.uploadedFiles.tokens,
            comment_file: this.uploadedFiles.comments,
            post_id: document.getElementById('postId').value.trim(),
            delay_config: {
                mode: delayMode
            },
            mention_enabled: mentionsEnabled
        };

        // Add delay configuration
        if (delayMode === 'random') {
            formData.delay_config.min = parseInt(document.getElementById('minDelay').value);
            formData.delay_config.max = parseInt(document.getElementById('maxDelay').value);
        } else {
            formData.delay_config.values = document.getElementById('delayValues').value.trim();
        }

        // Add mention configuration
        if (mentionsEnabled) {
            formData.mention_id = document.getElementById('mentionId').value.trim();
            formData.mention_name = document.getElementById('mentionName').value.trim();
        }

        return formData;
    }

    async stopTask() {
        const taskId = document.getElementById('stopTaskId').value.trim();
        
        if (!taskId) {
            this.showAlert('Please enter a Task ID', 'danger');
            return;
        }

        try {
            this.showLoading('Stopping task...');

            const response = await fetch('/stop_task', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ task_id: taskId })
            });

            const result = await response.json();

            if (result.success) {
                this.showAlert(result.message, 'success');
                document.getElementById('stopTaskId').value = '';
                this.loadRunningTasks();
            } else {
                this.showAlert(`Failed to stop task: ${result.error}`, 'danger');
            }
        } catch (error) {
            this.showAlert(`Error stopping task: ${error.message}`, 'danger');
        } finally {
            this.hideLoading();
        }
    }

    async loadRunningTasks() {
        try {
            const response = await fetch('/running_tasks');
            const result = await response.json();

            if (result.success) {
                this.displayRunningTasks(result.tasks);
            }
        } catch (error) {
            console.error('Error loading running tasks:', error);
        }
    }

    displayRunningTasks(tasks) {
        const container = document.getElementById('runningTasksList');
        
        if (tasks.length === 0) {
            container.innerHTML = `
                <div class="text-center p-3 text-muted">
                    <i class="fas fa-clock fa-2x mb-2"></i>
                    <p>No running tasks</p>
                </div>
            `;
            return;
        }

        container.innerHTML = tasks.map(task => `
            <div class="task-item p-3 border-bottom">
                <div class="d-flex justify-content-between align-items-start">
                    <div>
                        <div class="task-id mb-1">#${task.task_id}</div>
                        <div class="task-stats">
                            <small class="d-block">
                                <i class="fas fa-comments me-1"></i>
                                Comments: ${task.stats.comments_sent}
                            </small>
                            <small class="d-block">
                                <i class="fas fa-exclamation-triangle me-1"></i>
                                Errors: ${task.stats.errors}
                            </small>
                            <small class="d-block text-muted">
                                Started: ${new Date(task.stats.started_at).toLocaleTimeString()}
                            </small>
                        </div>
                    </div>
                    <div class="text-end">
                        <span class="status-badge status-running">
                            <i class="fas fa-play me-1"></i>Running
                        </span>
                        <button class="btn btn-sm btn-outline-info mt-2" 
                                onclick="app.showTaskStatus('${task.task_id}')">
                            <i class="fas fa-chart-line"></i>
                        </button>
                    </div>
                </div>
                ${task.stats.current_token ? `
                    <div class="mt-2">
                        <small class="text-muted">
                            <i class="fas fa-user me-1"></i>
                            Current: ${task.stats.current_token}
                        </small>
                    </div>
                ` : ''}
            </div>
        `).join('');
    }

    async showTaskStatus(taskId) {
        try {
            const response = await fetch(`/task_status/${taskId}`);
            const result = await response.json();

            if (result.success) {
                const stats = result.stats;
                const modalContent = document.getElementById('taskStatusContent');
                
                modalContent.innerHTML = `
                    <div class="row">
                        <div class="col-md-6">
                            <h6><i class="fas fa-info-circle me-2"></i>Task Information</h6>
                            <ul class="list-unstyled">
                                <li><strong>Task ID:</strong> ${taskId}</li>
                                <li><strong>Status:</strong> 
                                    <span class="status-badge status-${stats.status}">
                                        ${stats.status.charAt(0).toUpperCase() + stats.status.slice(1)}
                                    </span>
                                </li>
                                <li><strong>Started:</strong> ${new Date(stats.started_at).toLocaleString()}</li>
                            </ul>
                        </div>
                        <div class="col-md-6">
                            <h6><i class="fas fa-chart-bar me-2"></i>Statistics</h6>
                            <ul class="list-unstyled">
                                <li><strong>Comments Sent:</strong> ${stats.comments_sent}</li>
                                <li><strong>Errors:</strong> ${stats.errors}</li>
                                <li><strong>Success Rate:</strong> 
                                    ${stats.comments_sent + stats.errors > 0 ? 
                                        Math.round((stats.comments_sent / (stats.comments_sent + stats.errors)) * 100) + '%' : 
                                        'N/A'}
                                </li>
                            </ul>
                        </div>
                    </div>
                    ${stats.current_token ? `
                        <hr>
                        <h6><i class="fas fa-clock me-2"></i>Current Activity</h6>
                        <p><strong>Token:</strong> ${stats.current_token}</p>
                        <p><strong>Comment:</strong> ${stats.current_comment || 'N/A'}</p>
                    ` : ''}
                `;

                const modal = new bootstrap.Modal(document.getElementById('taskStatusModal'));
                modal.show();
            } else {
                this.showAlert(`Failed to load task status: ${result.error}`, 'danger');
            }
        } catch (error) {
            this.showAlert(`Error loading task status: ${error.message}`, 'danger');
        }
    }

    resetForm() {
        document.getElementById('taskForm').reset();
        document.getElementById('randomDelay').checked = true;
        document.getElementById('minDelay').value = 60;
        document.getElementById('maxDelay').value = 120;
        document.getElementById('mentionInputs').style.display = 'none';
        document.getElementById('randomDelayInputs').style.display = 'block';
        document.getElementById('accurateDelayInputs').style.display = 'none';
        this.uploadedFiles = {};
    }

    showAlert(message, type = 'info') {
        const alertsContainer = document.getElementById('alertsContainer');
        const alertId = 'alert-' + Date.now();
        
        const alertHTML = `
            <div id="${alertId}" class="alert alert-${type} alert-dismissible fade show fade-in" role="alert">
                <i class="fas fa-${this.getAlertIcon(type)} me-2"></i>
                ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            </div>
        `;
        
        alertsContainer.insertAdjacentHTML('beforeend', alertHTML);
        
        // Auto-dismiss after 5 seconds
        setTimeout(() => {
            const alertElement = document.getElementById(alertId);
            if (alertElement) {
                const alert = bootstrap.Alert.getOrCreateInstance(alertElement);
                alert.close();
            }
        }, 5000);
    }

    getAlertIcon(type) {
        switch (type) {
            case 'success': return 'check-circle';
            case 'danger': return 'exclamation-circle';
            case 'warning': return 'exclamation-triangle';
            default: return 'info-circle';
        }
    }

    showLoading(message = 'Loading...') {
        const existingLoader = document.getElementById('loadingAlert');
        if (existingLoader) existingLoader.remove();

        const alertsContainer = document.getElementById('alertsContainer');
        const loadingHTML = `
            <div id="loadingAlert" class="alert alert-info fade show fade-in" role="alert">
                <div class="d-flex align-items-center">
                    <div class="spinner-border spinner-border-sm me-3" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                    <div>${message}</div>
                </div>
            </div>
        `;
        
        alertsContainer.insertAdjacentHTML('beforeend', loadingHTML);
    }

    hideLoading() {
        const loadingAlert = document.getElementById('loadingAlert');
        if (loadingAlert) {
            loadingAlert.remove();
        }
    }

    // Utility method to format time
    formatTime(date) {
        return new Date(date).toLocaleString();
    }

    // Utility method to calculate duration
    calculateDuration(startTime) {
        const start = new Date(startTime);
        const now = new Date();
        const diff = now - start;
        
        const hours = Math.floor(diff / (1000 * 60 * 60));
        const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
        const seconds = Math.floor((diff % (1000 * 60)) / 1000);
        
        return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
    }
}

// Initialize the application when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    window.app = new CommentAutomation();
});
