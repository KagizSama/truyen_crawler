const chatArea = document.getElementById('chat-area');
const userInput = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');

// Generate unique session ID
const sessionId = 'session-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9);
console.log("Current Session ID:", sessionId);

// Initial focus
userInput.focus();

// Event Listeners
sendBtn.addEventListener('click', sendMessage);
userInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendMessage();
});

async function sendMessage() {
    const query = userInput.value.trim();
    if (!query) return;

    // Add User Message (NO AVATAR)
    addMessage(query, 'user');
    userInput.value = '';
    userInput.disabled = true;
    sendBtn.disabled = true;

    // Show Loading
    // Check if query looks like a URL to change status (more flexible regex)
    const isUrl = /https?:\/\//i.test(query.trim());
    const loadingText = isUrl ? "> CRAWLING DATA..." : "> THINKING...";

    const loadingId = addLoadingIndicator(loadingText);
    scrollToBottom();

    try {
        const response = await fetch('/api/v1/agent/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                query: query,
                session_id: sessionId
            })
        });

        const data = await response.json();

        // Remove Loading
        removeMessage(loadingId);

        if (response.ok) {
            addMessage(data.answer, 'bot', data.sources);
        } else {
            addMessage("Xin lỗi, hệ thống đang gặp sự cố: " + (data.detail || "Unknown error"), 'bot');
        }

    } catch (error) {
        removeMessage(loadingId);
        addMessage("Xin lỗi, không thể kết nối tới server.", 'bot');
        console.error(error);
    } finally {
        userInput.disabled = false;
        sendBtn.disabled = false;
        userInput.focus();
        scrollToBottom();
    }
}

function addMessage(text, sender, sources = []) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${sender}`;

    // Convert newlines to breaks for bot messages
    let formattedText = text;
    if (sender === 'bot') {
        formattedText = text.replace(/\n/g, '<br>');
    }

    // Auto-link URLs
    formattedText = formattedText.replace(
        /(https?:\/\/[^\s]+)/g,
        '<a href="$1" target="_blank" style="color: #fff; text-decoration: underline;">$1</a>'
    );

    let sourcesHtml = '';
    if (sources && sources.length > 0) {
        sourcesHtml = `
            <div class="sources-container">
                <button class="toggle-sources" onclick="toggleSources(this)">
                    <span>> VIEW SOURCES [${sources.length}]</span>
                </button>
                <div class="sources-list hidden">
                    ${sources.map(s => `
                        <div class="source-item">
                            >> ${s.story_title} | ${s.chapter_title}
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }

    // X-Style: No avatars, just content. 
    msgDiv.innerHTML = `
        <div class="content">
            ${formattedText}
            ${sourcesHtml}
        </div>
    `;

    chatArea.appendChild(msgDiv);
    return msgDiv;
}

function addLoadingIndicator(text = "> THINKING...") {
    const id = 'loading-' + Date.now();
    const msgDiv = document.createElement('div');
    msgDiv.className = 'message bot';
    msgDiv.id = id;
    msgDiv.innerHTML = `
        <div class="content">
            <span class="typing-line">${text}</span>
        </div>
    `;
    chatArea.appendChild(msgDiv);
    return id;
}

function removeMessage(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
}

function scrollToBottom() {
    chatArea.scrollTop = chatArea.scrollHeight;
}

// Global function for toggle
window.toggleSources = function (btn) {
    const list = btn.nextElementSibling;
    list.classList.toggle('hidden');
    // Simple ASCII arrow toggle
    const span = btn.querySelector('span');
    if (list.classList.contains('hidden')) {
        span.textContent = span.textContent.replace('v', '>');
    } else {
        span.textContent = span.textContent.replace('>', 'v');
    }
};
