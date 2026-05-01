/**
 * script.js — Frontend JavaScript for Health Insights AI Agent (HIA)
 * Handles: Chat widget, Flash message auto-dismiss, UI utilities
 */

// =====================
// Chat Widget
// =====================
(function initChat() {
  const toggleBtn   = document.getElementById('chatToggle');
  const chatBox     = document.getElementById('chatBox');
  const chatInput   = document.getElementById('chatInput');
  const sendBtn     = document.getElementById('chatSend');
  const messagesDiv = document.getElementById('chatMessages');

  if (!toggleBtn) return; // Only runs on pages where chat is shown

  // Conversation history to send to the AI for context
  let chatHistory = [];

  // --- Toggle chat box open/close ---
  toggleBtn.addEventListener('click', () => {
    chatBox.classList.toggle('open');
    if (chatBox.classList.contains('open')) {
      chatInput.focus();
      toggleBtn.textContent = '✖';
    } else {
      toggleBtn.textContent = '💬';
    }
  });

  // --- Send message on Enter key ---
  chatInput.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // --- Send message on button click ---
  sendBtn.addEventListener('click', sendMessage);

  /**
   * Appends a message bubble to the chat window.
   * @param {string} text - The message text.
   * @param {'user'|'ai'} sender - Who sent the message.
   */
  function appendMessage(text, sender) {
    const div = document.createElement('div');
    div.classList.add('msg', sender === 'user' ? 'msg-user' : 'msg-ai');
    div.textContent = text;
    messagesDiv.appendChild(div);
    // Scroll to bottom
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
  }

  /**
   * Shows a loading indicator in the chat while waiting for AI response.
   * Returns the indicator element so it can be removed later.
   */
  function showTypingIndicator() {
    const div = document.createElement('div');
    div.classList.add('msg', 'msg-ai');
    div.id = 'typingIndicator';
    div.innerHTML = '<span style="opacity:0.6;">🤖 Thinking…</span>';
    messagesDiv.appendChild(div);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
    return div;
  }

  /**
   * Main function: takes the user's input, sends to /chat API, shows reply.
   */
  async function sendMessage() {
    const message = chatInput.value.trim();
    if (!message) return;

    // Show user's message
    appendMessage(message, 'user');
    chatInput.value = '';
    sendBtn.disabled = true;

    // Add to history
    chatHistory.push({ role: 'user', content: message });

    // Show typing indicator
    const indicator = showTypingIndicator();

    try {
      const response = await fetch('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: message,
          history: chatHistory.slice(-6), // Keep last 6 messages for context
        }),
      });

      const data = await response.json();
      indicator.remove();

      if (data.reply) {
        appendMessage(data.reply, 'ai');
        // Add AI reply to history
        chatHistory.push({ role: 'assistant', content: data.reply });
        // Keep history manageable (last 10 exchanges)
        if (chatHistory.length > 20) chatHistory = chatHistory.slice(-20);
      } else {
        appendMessage('Sorry, I encountered an error. Please try again.', 'ai');
      }
    } catch (error) {
      indicator.remove();
      appendMessage('⚠️ Connection error. Please check your internet and try again.', 'ai');
    } finally {
      sendBtn.disabled = false;
      chatInput.focus();
    }
  }
})();


// =====================
// Flash Message Auto-Dismiss
// =====================
(function initFlashDismiss() {
  const container = document.getElementById('flashContainer');
  if (!container) return;

  // Auto-remove flashes after 5 seconds
  setTimeout(() => {
    container.style.transition = 'opacity 0.5s ease';
    container.style.opacity = '0';
    setTimeout(() => container.remove(), 500);
  }, 5000);
})();


// =====================
// Smooth scroll for anchor links
// =====================
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
  anchor.addEventListener('click', function (e) {
    const target = document.querySelector(this.getAttribute('href'));
    if (target) {
      e.preventDefault();
      target.scrollIntoView({ behavior: 'smooth' });
    }
  });
});


// =====================
// Active nav link highlighting
// =====================
(function highlightActiveNav() {
  const currentPath = window.location.pathname;
  document.querySelectorAll('.navbar-links a').forEach(link => {
    if (link.getAttribute('href') === currentPath) {
      link.classList.add('active');
    }
  });
})();
