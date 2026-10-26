document.querySelectorAll('[data-repeat-kind]').forEach(function (select) {
  function syncRepeatFields() {
    const form = select.closest('form');
    const weekday = form.querySelector('[data-repeat-weekday]');
    const monthday = form.querySelector('[data-repeat-monthday]');
    const reminder = form.querySelector('input[name="remind_at"]');
    if (weekday) weekday.hidden = select.value !== 'weekly';
    if (monthday) monthday.hidden = select.value !== 'monthly';
    if (reminder) reminder.required = select.value !== 'none';
  }
  select.addEventListener('change', syncRepeatFields);
  syncRepeatFields();
});

document.querySelectorAll('form[data-confirm]').forEach(function (form) {
  form.addEventListener('submit', function (event) {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  });
});
