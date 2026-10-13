(() => {
  // Register before the browser reveals a destination document. Loading this
  // observer in the head prevents skipped incoming animations from rejecting
  // before the navigation controls at the end of the body are initialized.
  for (const type of ['pageswap', 'pagereveal']) {
    window.addEventListener(type, event => {
      event.viewTransition?.ready.catch(error => {
        // Chromium can report an opt-out cancellation as a plain Error rather
        // than a DOMException. Handle that specific cancellation here too;
        // unrelated animation failures must still remain observable.
        const optedOut = error.message ===
          'Transition was aborted because of invalid state. ViewTransition opt-in disabled';
        if (!['AbortError', 'InvalidStateError'].includes(error.name) && !optedOut) throw error;
      });
    });
  }
})();
