(() => {
  const format = value => {
    if (!Number.isFinite(value)) return '';
    const rounded = Math.round(value * 100) / 100;
    return Number.isInteger(rounded) ? String(rounded) : String(rounded).replace(/0+$/, '').replace(/\.$/, '');
  };

  const detail = document.querySelector('[data-v10-recipe-detail]');
  if (detail) {
    const inputs = [...detail.querySelectorAll('[data-raw-weight]')];
    const factors = {g:1, '克':1, kg:1000, '千克':1000, '公斤':1000, '斤':500, '两':50};
    const base = Number(detail.dataset.baseAmount || 0);
    const fallbackFactor = inputs.some(input => input.dataset.rawId) ? 1 : (factors[inputs[0]?.dataset.unit.trim().toLowerCase()] || 1);
    let revision = Date.now();
    const refresh = (save = false) => {
      const valid = inputs.every(input => input.checkValidity() && Number.isFinite(Number(input.value)) && Number(input.value) > 0 && factors[input.dataset.unit.trim().toLowerCase()]);
      const target = inputs.reduce((sum, input) => sum + Number(input.value) * (factors[input.dataset.unit.trim().toLowerCase()] || 0), 0) / fallbackFactor;
      const ready = valid && Number.isFinite(target) && target > 0;
      detail.querySelector('[data-raw-weight-error]').textContent = ready ? '' : '请填写有效的原料重量';
      detail.querySelectorAll('[data-recipe-print-link]').forEach(link => {
        link.setAttribute('aria-disabled', String(!ready));
        const url = new URL(link.href, window.location.href);
        url.searchParams.delete('raw');
        if (ready) {
          url.searchParams.set('amount', String(target));
          inputs.forEach(input => { if (input.dataset.rawId) url.searchParams.append('raw', `${input.dataset.rawId}:${input.value}`); });
        }
        link.href = url.href;
      });
      if (!ready) return;
      if (save) {
        revision = Math.max(Date.now(), revision + 1);
        const currentRevision = revision;
        const body = new URLSearchParams({csrf:detail.dataset.csrf, version_id:detail.dataset.versionId, revision:String(revision), amount:String(target)});
        inputs.forEach(input => { if (input.dataset.rawId) body.append('raw', `${input.dataset.rawId}:${input.value}`); });
        const status = detail.querySelector('[data-raw-weight-error]');
        status.textContent = '正在保存…';
        fetch(detail.dataset.saveUrl, {method:'POST', body, credentials:'same-origin', keepalive:true, headers:{Accept:'application/json'}})
          .then(response => { if (!response.ok || response.redirected) throw new Error('save'); return response.json(); })
          .then(result => { if (!result.ok) throw new Error('save'); if (revision === currentRevision) status.textContent = '已保存'; })
          .catch(() => { if (revision === currentRevision) status.textContent = '保存失败，请重新修改重量后重试'; });
      }
      detail.querySelectorAll('.v10-ingredient[data-ingredient-amount]').forEach(row => {
        const raw = row.dataset.ingredientAmount;
        const amount = Number(raw);
        const out = row.querySelector('[data-scaled]');
        if (!out || raw === '' || !Number.isFinite(amount)) return;
        const value = row.dataset.scaleMode === 'proportional' && base > 0 ? amount * target / base : amount;
        out.textContent = format(value);
      });
    };
    inputs.forEach(input => input.addEventListener('input', () => refresh(true)));
    detail.querySelectorAll('[data-recipe-print-link]').forEach(link => link.addEventListener('click', event => {
      if (link.getAttribute('aria-disabled') === 'true') { event.preventDefault(); inputs.find(input => !input.checkValidity() || Number(input.value) <= 0)?.reportValidity(); }
    }));
    refresh();
  }

  const editor = document.querySelector('[data-v10-recipe-editor]');
  if (editor) {
    const ingredientList = editor.querySelector('[data-ingredient-list]');
    const ingredientTpl = document.getElementById('v10IngredientTemplate');
    const stepList = editor.querySelector('[data-step-list]');
    const stepTpl = document.getElementById('v10StepTemplate');
    const renumberSteps = () => {
      stepList?.querySelectorAll('.v10-step-edit').forEach((row, idx) => {
        const label = row.querySelector('.v10-step-edit-head strong');
        if (label) label.textContent = `步骤 ${idx + 1}`;
      });
    };
    if (!editor.hasAttribute('data-grouped-recipe-editor')) editor.querySelector('[data-add-ingredient]')?.addEventListener('click', () => {
      if (ingredientTpl && ingredientList) ingredientList.appendChild(ingredientTpl.content.cloneNode(true));
    });
    editor.querySelector('[data-add-step]')?.addEventListener('click', () => {
      if (stepTpl && stepList) stepList.appendChild(stepTpl.content.cloneNode(true));
      renumberSteps();
    });
    editor.addEventListener('click', event => {
      const button = event.target.closest('[data-remove-row]');
      if (!button) return;
      button.closest('.v10-edit-row,.v10-step-edit')?.remove();
      renumberSteps();
    });
    renumberSteps();
  }

  // Version rendering is server-driven through request.app.version in base.html.
  // Do not overwrite it in JavaScript; this keeps UI, /health and deploy checks aligned.
  if (!document.querySelector('link[href*="/static/v12.css"]')) {
    const link = document.createElement('link');
    link.rel = 'stylesheet'; link.href = '/static/v12.css?v=1200';
    document.head.appendChild(link);
  }
  if (location.pathname.startsWith('/life')) {
    const nav = document.querySelector('.bottom-nav');
    if (nav) {
      nav.innerHTML = '<a href="/life" class="nav-item">⌂<span>生活</span></a><a href="/life/recipes" class="nav-item">▤<span>菜谱</span></a><a href="/life/tools" class="nav-item">⌗<span>工具</span></a>';
      nav.style.gridTemplateColumns = 'repeat(3,1fr)';
    }
  }
  if (!document.querySelector('script[src*="/static/v12.js"]')) {
    const script = document.createElement('script');
    script.src = '/static/v12.js?v=1200';
    document.body.appendChild(script);
  }
})();
