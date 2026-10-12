// Exercise the actual row-summary handler independently of the workflow refresh.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('app/static/v028.js', 'utf8');
const handler = source.slice(source.indexOf('  const updateSummary ='), source.indexOf('  const updatePaymentRow ='));
function control() {
  const classes = new Set(['disabled', 'secondary']);
  return {attrs: {'aria-disabled': 'true'}, classList: {
    toggle(name, enabled) { enabled ? classes.add(name) : classes.delete(name); },
    contains(name) { return classes.has(name); }
  }, setAttribute(name, value) { this.attrs[name] = value; }};
}
const excel = control(), txt = control();
const elements = {paymentExcelButton: excel, paymentTxtButton: txt};
const sandbox = {document: {getElementById: id => elements[id] || null}, root: {querySelector: () => null}, money: String};
vm.createContext(sandbox);
vm.runInContext(handler + ';globalThis.update = updateSummary;', sandbox);
function expectReady(ready) {
  for (const button of [excel, txt]) {
    assert.equal(button.attrs['aria-disabled'], String(!ready));
    assert.equal(button.classList.contains('primary'), ready);
    assert.equal(button.classList.contains('disabled'), !ready);
  }
}
sandbox.update({pending: 0, txt_ready: true}); expectReady(true);
sandbox.update({pending: 1, txt_ready: false}); expectReady(false);
sandbox.update({pending: 0}); expectReady(false); // Missing readiness never enables export.
sandbox.update({pending: 0, txt_ready: true}); expectReady(true);
delete elements.paymentExcelButton;
assert.doesNotThrow(() => sandbox.update({pending: 1, txt_ready: false}));
console.log('Both export buttons follow row-review readiness without another workflow request');
