'use strict';
const INVITE = /^[A-Za-z0-9_-]{24,128}$/;
function parseInvite(value) {
  const text = String(value || '').trim();
  if (INVITE.test(text)) return text;
  const match = text.match(/^https:\/\/jituan\.zbassistant\.site\/number-submit\/([A-Za-z0-9_-]{24,128})(?:\/pending)?(?:[?#].*)?$/);
  return match ? match[1] : '';
}
function inviteFromOptions(options) {
  try {
    const raw = options.invite || decodeURIComponent(options.scene || '').replace(/^invite=/, '');
    return parseInvite(raw);
  } catch (_) { return ''; }
}
module.exports = {parseInvite, inviteFromOptions};
