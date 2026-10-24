// Recipe groups are a presentation of existing ingredient_group values.
// Keep one hidden value per material so the established version API stays aligned.
(() => {
  const editor = document.querySelector('[data-grouped-recipe-editor]');
  if (!editor) return;
  const list = editor.querySelector('[data-ingredient-list]');
  const groups = () => [...list.querySelectorAll('[data-recipe-group]')];
  const sync = () => {
    const cards = groups();
    const names = cards.map(card => card.querySelector('[data-group-name]').value.trim());
    cards.forEach((card, index) => {
      const input = card.querySelector('[data-group-name]');
      input.setCustomValidity(names.filter(name => name === names[index]).length > 1 ? '环节名称重复，请使用不同名称。' : '');
      card.querySelectorAll('[name=ingredient_group]').forEach(field => { field.value = names[index] || '配料'; });
      card.querySelectorAll('[data-material-group]').forEach(select => {
        select.replaceChildren(...names.map((name, targetIndex) => {
          const option = document.createElement('option');
          option.value = String(targetIndex);
          option.textContent = name || '配料';
          option.selected = targetIndex === index;
          return option;
        }));
      });
      card.querySelector('[data-group-up]').disabled = index === 0;
      card.querySelector('[data-group-down]').disabled = index === cards.length - 1;
    });
    editor.querySelector('[data-empty-groups]').hidden = cards.length > 0;
  };
  editor.addEventListener('input', event => {
    if (event.target.matches('[data-group-name]')) sync();
  });
  editor.addEventListener('change', event => {
    if (event.target.matches('[data-material-group]')) {
      const target = groups()[Number(event.target.value)];
      const row = event.target.closest('.recipe-material');
      if (target && row) target.querySelector('[data-group-materials]').append(row);
      sync();
    }
    if (event.target.matches('[name=ingredient_mode]')) {
      event.target.closest('.recipe-material').querySelector('[data-mode-label]').textContent = event.target.selectedOptions[0].textContent;
    }
  });
  editor.addEventListener('click', event => {
    const button = event.target.closest('button');
    if (!button) return;
    let card = button.closest('[data-recipe-group]');
    if (button.matches('[data-add-group]')) {
      list.append(editor.querySelector('#recipeGroupTemplate').content.cloneNode(true));
      card = list.lastElementChild;
      let number = groups().length;
      const existing = groups().slice(0, -1).map(group => group.querySelector('[data-group-name]').value.trim());
      while (existing.includes(`环节 ${number}`)) number++;
      const input = card.querySelector('[data-group-name]');
      input.value = `环节 ${number}`;
      input.focus();
      input.select();
    } else if (card && button.matches('[data-add-ingredient]')) {
      const materials = card.querySelector('[data-group-materials]');
      materials.append(editor.querySelector('#v10IngredientTemplate').content.cloneNode(true));
      materials.lastElementChild.querySelector('[name=ingredient_name]').focus();
    } else if (button.matches('[data-remove-material]')) {
      button.closest('.recipe-material').remove();
    } else if (card && button.matches('[data-delete-group]')) {
      if (card.querySelector('.recipe-material') && !window.confirm('删除此环节及其中全部物料？保存前仍可返回放弃修改。')) return;
      card.remove();
    } else if (card && button.matches('[data-group-up]') && card.previousElementSibling) {
      list.insertBefore(card, card.previousElementSibling);
    } else if (card && button.matches('[data-group-down]') && card.nextElementSibling) {
      list.insertBefore(card.nextElementSibling, card);
    }
    sync();
  });
  editor.querySelector('form').addEventListener('submit', sync);
  sync();
})();
