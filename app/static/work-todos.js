function syncRepeatFields(select) {
  const form = select.closest('form');
  const weekday = form.querySelector('[data-repeat-weekday]');
  const monthday = form.querySelector('[data-repeat-monthday]');
  const reminder = form.querySelector('input[name="remind_at"]');
  if (weekday) weekday.hidden = select.value !== 'weekly';
  if (monthday) monthday.hidden = select.value !== 'monthly';
  if (reminder) reminder.required = select.value !== 'none';
}

document.querySelectorAll('[data-repeat-kind]').forEach(syncRepeatFields);
document.addEventListener('change', event => {
  if (event.target.matches('[data-repeat-kind]')) syncRepeatFields(event.target);
});
document.addEventListener('submit', event => {
  const form = event.target;
  if (form.matches('.wt-shell form[data-confirm]') && !window.confirm(form.dataset.confirm)) {
    event.preventDefault();
  }
});
