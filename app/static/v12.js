(() => {
  const root = document.querySelector('[data-v12-tools]');
  if (!root) return;
  const n = (v) => Number(v || 0);
  const fmt = (v) => Number.isFinite(v) ? (Math.round(v * 100) / 100).toString() : '-';

  const saltRules = {
    '收汁': {ratio: .01, soup: .2},
    '快炒': {ratio: .01, soup: .5},
    '炖汤': {ratio: .008, soup: 0},
    '清汤': {ratio: .006, soup: 0},
    '主食': {ratio: .006, soup: 0},
  };
  const seasoningRules = {
    '生抽': {mode: 'soy', sodium: 1},
    '老抽': {mode: 'soy', sodium: 1},
    '料酒': {mode: 'soy', sodium: .1},
    '郫县豆瓣酱': {mode: 'percent', sodium: 8},
    '番茄酱': {mode: 'percent', sodium: 2},
    '味极鲜': {mode: 'percent', sodium: .88},
    '豆瓣酱': {mode: 'unset', sodium: 0},
    '牛排酱': {mode: 'percent', sodium: 2},
  };
  const saltFrom = (name, weight) => {
    const r = seasoningRules[name];
    if (!r || r.mode === 'unset') return 0;
    if (r.mode === 'soy') return weight / 1.15 / 15 * r.sodium * 2.5;
    return weight / 100 * r.sodium * 2.5;
  };
  const saltOutput = (key, value) => {
    const el = root.querySelector(`[data-v12-out="${key}"]`);
    if (el) el.textContent = `${fmt(value)} g`;
  };
  const refreshSalt = () => {
    const method = document.getElementById('v12SaltMethod')?.value || '收汁';
    const weight = n(document.getElementById('v12SaltWeight')?.value);
    const coating = n(document.getElementById('v12Coating')?.value);
    const adjusted = weight * (coating === 1 ? 1.3 : coating === 2 ? 1.5 : 1);
    const rule = saltRules[method];
    const soup = adjusted * rule.soup;
    const total = (adjusted + soup) * rule.ratio;
    let seasoning = 0;
    root.querySelectorAll('[data-v12-seasoning]').forEach(input => {
      seasoning += saltFrom(input.dataset.v12Seasoning, n(input.value));
    });
    const base = total * .3;
    const add = total - seasoning - base;
    saltOutput('adjusted', adjusted); saltOutput('soup', soup); saltOutput('total', total);
    saltOutput('seasoning', seasoning); saltOutput('base', base); saltOutput('add', add);
    refreshSaltTable();
  };

  const sauceRecipes = {
    '糖醋汁（大）': [['白糖',94],['6度米醋',94],['生抽',5],['盐',3],['香油',8],['清水',30],['淀粉',2]],
    '糖醋汁（中）': [['白糖',55],['6度白醋',55],['生抽',15],['老抽',4],['盐',2],['淀粉',7],['清水',35]],
    '糖醋汁（小）': [['白糖',20],['6度白醋',20]],
    '红烧汁': [['生抽',23],['老抽',3],['陈醋',6],['白糖',4],['蚝油',8]],
    '宫保汁': [['生抽',10],['老抽',5],['白糖',30],['陈醋',30],['清水',20],['淀粉',6]],
    '蒲烧汁': [['生抽',15],['老抽',5],['味淋',20],['清酒',20],['白糖',10],['清水',180]],
    '腌肉': [['牛排酱',15],['番茄酱',15],['小料',1.5],['黑胡椒',1.5],['白芝麻',5],['蒜香粉',2.5],['香油',5]],
  };
  const refreshSauce = () => {
    const weight = n(document.getElementById('v12SauceWeight')?.value);
    const type = document.getElementById('v12SauceType')?.value || '糖醋汁（大）';
    const box = root.querySelector('[data-v12-sauce-results]'); if (!box) return;
    box.innerHTML = sauceRecipes[type].map(([name, base]) => `<div><span>${name}</span><strong>${fmt(base * weight / 500)} g</strong></div>`).join('');
  };
  const refreshSaltTable = () => {
    const box = root.querySelector('[data-v12-salt-table]'); if (!box) return;
    box.innerHTML = Object.entries(seasoningRules).map(([name, rule]) => {
      const input = root.querySelector(`[data-v12-seasoning="${name}"]`);
      const weight = n(input?.value);
      const salt = saltFrom(name, weight);
      const formula = rule.mode === 'soy' ? '原表：重量÷1.15÷15×含钠量×2.5' : rule.mode === 'percent' ? '原表：重量÷100×含钠量×2.5' : '原表未设置含钠值';
      return `<div><b>${name}</b><span>${weight}g → ${fmt(salt)}g 盐</span><small>${formula}</small></div>`;
    }).join('');
  };

  root.addEventListener('input', (e) => {
    if (e.target.closest('#salt-tool')) refreshSalt();
    if (e.target.closest('#sauce-tool')) refreshSauce();
  });
  root.addEventListener('change', (e) => {
    if (e.target.closest('#salt-tool')) refreshSalt();
    if (e.target.closest('#sauce-tool')) refreshSauce();
  });
  refreshSalt(); refreshSauce();
})();
