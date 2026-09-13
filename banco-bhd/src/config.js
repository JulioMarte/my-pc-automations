const path = require('path');
require('dotenv').config({ path: path.resolve(__dirname, '..', '.env'), quiet: true });

const root = path.resolve(__dirname, '..');

const list = (value, fallback) =>
  value
    ? value.split(',').map((item) => item.trim()).filter(Boolean)
    : fallback;

const securityAnswers = [];
for (let index = 1; index <= 20; index += 1) {
  const question = process.env[`BHD_SECURITY_Q${index}`];
  const answer = process.env[`BHD_SECURITY_A${index}`];
  if (question && answer) securityAnswers.push({ question, answer });
}

const cardCodes = {};
for (const entry of (process.env.BHD_CARD_CODES || '').split(',')) {
  const [position, code] = entry.split(':').map((part) => part.trim());
  if (position && code) cardCodes[position] = code;
}

module.exports = {
  root,
  profileDir: path.join(root, 'profile'),
  recordingsDir: path.join(root, 'recordings'),
  stateDir: path.join(root, 'state'),
  loginUrl: process.env.BHD_LOGIN_URL || 'https://ibp.bhd.com.do/#/login',
  user: process.env.BHD_USER || '',
  password: process.env.BHD_PASSWORD || '',
  securityAnswers,
  cardNumber: process.env.BHD_CARD_NUMBER || '',
  cardCodes,
  channel: process.env.BHD_CHANNEL || 'chrome',
  engine: process.env.BHD_ENGINE || 'patchright',
  mode: process.env.BHD_MODE || (process.env.BHD_HEADED === '1' ? 'visible' : 'hidden'),
  human: process.env.BHD_HUMAN !== '0',
  emailOtp: process.env.BHD_EMAIL_OTP !== '0',
  emailUrl: process.env.BHD_EMAIL_URL || 'https://outlook.live.com/mail/0/inbox',
  otpSender: (process.env.BHD_OTP_SENDER || 'bhd').toLowerCase(),
  accountName: process.env.BHD_ACCOUNT_NAME || 'Cuenta',
  movementsRange: process.env.BHD_MOVEMENTS_RANGE || 'Último mes',
  securityTimeoutMs: Number(process.env.BHD_SECURITY_TIMEOUT_MS || 900000),
  cardHints: list(process.env.BHD_CARD_HINTS, [
    'tarjeta de clave',
    'tarjeta de claves',
    'codigo de la tarjeta',
    'código de la tarjeta',
  ]),
  otpHints: list(process.env.BHD_OTP_HINTS, [
    'codigo de verificacion',
    'código de verificación',
    'codigo temporal',
    'código temporal',
    'codigo enviado',
    'código enviado',
    'verificacion de dos pasos',
    'verificación de dos pasos',
    'otp',
  ]),
  securityHints: list(process.env.BHD_SECURITY_HINTS, [
    'pregunta de seguridad',
    'respuesta de seguridad',
    'verificacion de identidad',
    'verificación de identidad',
    'nuevo dispositivo',
  ]),
  loggedHints: list(process.env.BHD_LOGGED_HINTS, [
    'cerrar sesion',
    'cerrar sesión',
    'mi cuenta',
    'transferencias',
    'pagos',
  ]),
  selectors: {
    user: process.env.BHD_SEL_USER || '',
    password: process.env.BHD_SEL_PASSWORD || '',
    submit: process.env.BHD_SEL_SUBMIT || '',
    loggedIn: process.env.BHD_SEL_LOGGED_IN || '',
  },
};
