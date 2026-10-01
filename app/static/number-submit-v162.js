(() => {
  'use strict';
  const rows = document.getElementById('number-inputs');
  const add = document.getElementById('add-number');
  if (!rows || !add) return;
  add.addEventListener('click', () => {
    const count = rows.querySelectorAll('input[name="number"]').length;
    if (count >= 100) return;
    const label = document.createElement('label');
    label.className = 'number-input-row';
    const caption = document.createElement('span');
    caption.textContent = `号码 ${count + 1}`;
    const input = document.createElement('input');
    input.name = 'number';
    input.inputMode = 'tel';
    input.autocomplete = 'tel';
    input.maxLength = 64;
    input.placeholder = '请输入号码';
    label.append(caption, input);
    rows.append(label);
    add.disabled = count + 1 >= 100;
    input.focus();
  });
})();
