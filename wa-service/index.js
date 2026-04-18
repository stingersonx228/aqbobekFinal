const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode');
const express = require('express');
const axios = require('axios');
const fs = require('fs');

const app = express();
app.use(express.json());

const PORT = process.env.PORT || 3000;
const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_URL || 'http://127.0.0.1:8001/internal-webhook';

// Initialize WhatsApp Client with Local Session (persists login)
const client = new Client({
    authStrategy: new LocalAuth(),
    puppeteer: {
        args: ['--no-sandbox']
    }
});

// Event: Generate QR Code
client.on('qr', (qr) => {
    console.log('QR Code received. Saving to qr.png...');
    qrcode.toFile('../qr.png', qr, {
        color: {
            dark: '#000000',
            light: '#FFFFFF'
        }
    }, function (err) {
        if (err) throw err;
        console.log('QR code saved as qr.png in the project root. Please open it and scan.');
    });
});

// Event: Authenticated
client.on('ready', () => {
    console.log('WhatsApp Client is Ready!');
});

// Event: Receive Message
client.on('message', async (message) => {
    // Игнорируем статусы (Истории WhatsApp)
    if (message.from === 'status@broadcast' || message.isStatus) {
        return;
    }

    console.log(`Received message from ${message.from}: ${message.body}`);
    
    try {
        // Send message to Python Backend
        await axios.post(PYTHON_BACKEND_URL, {
            from: message.from,
            body: message.body,
            isGroupMsg: message.isGroupMsg
        });
    } catch (error) {
        console.error('Error sending message to Python backend:', error.message);
    }
});

client.initialize();

// Express API to allow Python to send messages
app.post('/send', async (req, res) => {
    const { to, text } = req.body;
    
    if (!to || !text) {
        return res.status(400).json({ error: 'Missing "to" or "text"' });
    }

    try {
        await client.sendMessage(to, text);
        res.json({ status: 'sent' });
    } catch (error) {
        console.error('Error sending WhatsApp message:', error);
        res.status(500).json({ error: 'Failed to send message' });
    }
});

app.listen(PORT, () => {
    console.log(`WhatsApp Bridge Server running on port ${PORT}`);
});
