(() => {
  // Register before the browser reveals a destination document. Loading this
  // observer in the head prevents skipped incoming animations from rejecting
  // before the navigation controls at the end of the body are initialized.
  for (const type of ['pageswap', 'pagereveal']) {
    window.addEventListener(type, event => {
      event.viewTransition?.ready.catch(error => {
        if (!['AbortError', 'InvalidStateError'].includes(error.name)) throw error;
      });
    });
  }
})();
