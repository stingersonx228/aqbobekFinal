const path = require('path');
require('dotenv').config({ path: path.join(__dirname, '../.env') });
const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode');
const express = require('express');
const axios = require('axios');
const fs = require('fs');

const app = express();
app.use(express.json());

const PORT = process.env.WA_PORT || 3000;
const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_URL || 'http://127.0.0.1:8001/internal-webhook';
const INTERNAL_SECRET = process.env.INTERNAL_SECRET_TOKEN;

const client = new Client({
    authStrategy: new LocalAuth(),
    puppeteer: {
        headless: true,
        args: ['--no-sandbox', '--disable-setuid-sandbox']
    }
});

// Event: Generate QR Code and save to PNG
client.on('qr', (qr) => {
    console.log('--- NEW QR CODE GENERATED ---');
    const qrPath = path.join(__dirname, '../qr.png');
    
    qrcode.toFile(qrPath, qr, {
        width: 600, // Делаем картинку большой и четкой
        margin: 2,
        color: {
            dark: '#000000',
            light: '#FFFFFF'
        }
    }, function (err) {
        if (err) {
            console.error('Failed to save QR code:', err);
        } else {
            console.log('✅ Fresh QR code saved to qr.png. OPEN IT AND SCAN!');
        }
    });
});

client.on('ready', () => {
    console.log('✅ WhatsApp Client is Ready!');
    // Удаляем файл после успешного входа, чтобы не путаться
    const qrPath = path.join(__dirname, '../qr.png');
    if (fs.existsSync(qrPath)) fs.unlinkSync(qrPath);
});

client.on('message', async (message) => {
    if (message.from === 'status@broadcast' || message.isStatus) return;
    
    console.log(`📩 Received from ${message.from}: ${message.body}`);
    try {
        let media_data = null;
        let media_mimetype = null;
        
        if (message.hasMedia) {
            const media = await message.downloadMedia();
            if (media && media.mimetype && media.mimetype.startsWith('audio/')) {
                console.log(`🎤 Received Voice Message from ${message.from}`);
                media_data = media.data; // Base64 string
                media_mimetype = media.mimetype;
            }
        }

        await axios.post(PYTHON_BACKEND_URL, {
            message_id: message.id._serialized, // SEND UNIQUE ID
            from: message.from,
            body: message.body,
            user_name: message._data.notifyName || message.from,
            platform: "whatsapp",
            audio_base64: media_data,
            audio_mimetype: media_mimetype
        }, {
            headers: { 'X-Internal-Token': INTERNAL_SECRET }
        });
    } catch (error) {
        console.error('❌ Backend error:', error.message);
    }
});

client.initialize();

app.post('/send', async (req, res) => {
    const { to, text } = req.body;
    try {
        await client.sendMessage(to, text);
        res.json({ status: 'sent' });
    } catch (error) {
        res.status(500).json({ error: 'Failed to send' });
    }
});

app.listen(PORT, () => {
    console.log(`🚀 WhatsApp Bridge running on port ${PORT}`);
});
