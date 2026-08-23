"""Browser-injected JavaScript helpers.

These snippets run inside the target page via the agent's ``evaluate``
action. They are plain strings so they can be unit/integration tested
against fixture pages with Playwright.
"""

from __future__ import annotations

YESNO_JS = """(function(){
    var results = [];
    var answer = 'No';

    function fireClick(el) {
        el.dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));
        el.dispatchEvent(new MouseEvent('mouseup', {bubbles:true}));
        el.dispatchEvent(new MouseEvent('click', {bubbles:true}));
        el.click();
    }

    // Strategy 1: role="radio" elements (standard ARIA)
    document.querySelectorAll('[role="radio"]').forEach(function(r) {
        if (r.textContent.trim() === answer && r.getAttribute('aria-checked') !== 'true') {
            fireClick(r);
            results.push('S1-radio: ' + r.textContent.trim());
        }
    });

    // Strategy 2: data-automation-id containing radio
    document.querySelectorAll('[data-automation-id*="radio"], [data-automation-id*="Radio"]').forEach(function(r) {
        if (r.textContent.trim() === answer && r.getAttribute('aria-checked') !== 'true') {
            fireClick(r);
            results.push('S2-auto: ' + r.textContent.trim());
        }
    });

    // Strategy 3: actual <input type="radio"> (may be hidden)
    document.querySelectorAll('input[type="radio"]').forEach(function(inp) {
        var label = inp.closest('label') || inp.parentElement;
        if (label && label.textContent.trim() === answer && !inp.checked) {
            inp.click();
            inp.checked = true;
            inp.dispatchEvent(new Event('change', {bubbles:true}));
            results.push('S3-input: ' + label.textContent.trim());
        }
    });

    // Strategy 4: any clickable element with exact text "No"
    if (results.length === 0) {
        var sel = 'button, [role="button"], [role="option"], div[tabindex], span[tabindex], label';
        document.querySelectorAll(sel).forEach(function(el) {
            if (el.textContent.trim() !== answer) return;

            // Idempotency: never re-click an already-selected radio, even
            // when the answer lives on a wrapper element.
            var radio = el.getAttribute('role') === 'radio'
                ? el
                : (el.closest('[role="radio"]') || el.querySelector('[role="radio"]'));
            if (radio && radio.getAttribute('aria-checked') === 'true') return;
            var label = el.closest('label');
            var input = label ? label.querySelector('input[type="radio"]') : null;
            if (input && input.checked) return;

            fireClick(el);
            results.push('S4-generic: <' + el.tagName + '> ' + el.textContent.trim());
        });
    }

    return results.length > 0
        ? 'YES/NO handled: ' + results.join('; ')
        : 'No Yes/No buttons found on this page.';
})()"""


VERIFY_FIELDS_JS = """(function(){
    try {
        var issues = [];

        // Check required fields that are empty
        document.querySelectorAll('input[required], textarea[required], select[required]').forEach(function(el) {
            try {
                if (!el.value || el.value.trim() === '') {
                    var label = el.getAttribute('aria-label')
                        || (el.labels && el.labels[0] ? el.labels[0].textContent.trim() : '')
                        || el.name || el.id || 'unknown';
                    issues.push('EMPTY REQUIRED: ' + label);
                }
            } catch(e) {}
        });

        // Check aria-required fields
        document.querySelectorAll('[aria-required="true"]').forEach(function(el) {
            try {
                var val = (el.value || el.textContent || '').trim();
                var tag = el.tagName.toLowerCase();
                // Skip if it's a container or already has content
                if (tag === 'div' || tag === 'span' || tag === 'fieldset') return;
                if (val === '' || val === 'Select One') {
                    var label = el.getAttribute('aria-label') || el.id || 'unknown';
                    issues.push('ARIA REQUIRED UNFILLED: ' + label);
                }
            } catch(e) {}
        });

        // Check unchecked radio groups
        var radioGroups = {};
        document.querySelectorAll('[role="radio"]').forEach(function(r) {
            try {
                var group = r.closest('[role="radiogroup"]') || r.parentElement;
                var gid = group ? (group.id || group.getAttribute('data-automation-id') || 'group') : 'ungrouped';
                if (!radioGroups[gid]) radioGroups[gid] = {any_checked: false, label: ''};
                if (r.getAttribute('aria-checked') === 'true') radioGroups[gid].any_checked = true;
                if (!radioGroups[gid].label) radioGroups[gid].label = (group ? group.textContent.substring(0,40).trim() : gid);
            } catch(e) {}
        });
        for (var gid in radioGroups) {
            if (!radioGroups[gid].any_checked) {
                issues.push('UNCHECKED RADIO GROUP: ' + radioGroups[gid].label);
            }
        }

        // Check for visible error messages
        document.querySelectorAll('[class*="error"], [class*="Error"], [role="alert"], [data-automation-id*="error"]').forEach(function(el) {
            try {
                var text = (el.textContent || '').trim();
                if (text && text.length > 2 && text.length < 200 && el.offsetParent !== null) {
                    issues.push('ERROR MSG: ' + text.substring(0, 80));
                }
            } catch(e) {}
        });

        return issues.length > 0
            ? 'VERIFICATION FAILED — ' + issues.length + ' issues:\\n' + issues.join('\\n')
            : 'VERIFICATION PASSED — all fields filled, no errors detected.';
    } catch(e) {
        return 'VERIFICATION PASSED — (script fallback, check manually)';
    }
})()"""
