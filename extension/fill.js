// Runs inside the application page when you click "Fill this form". It only types into empty fields it recognises,
// never clicks anything, never uploads files, and leaves salary, visa, demographic and consent questions to you.
// Same rules as the app's own form helper (jobagent/agents/formfill.py).
window.__offerpilotFill = function (values, coverLetter) {
  const NEVER = /password|captcha|gender|race|ethnic|veteran|disabilit|salary|compensation|ctc|sponsor|authori[sz]|visa|notice|pronoun|birth|\bdob\b|ssn|social security|referr|hear about|expected|school|university|degree|reference|relocat|citizen|clearance|criminal|consent|agree|terms|privacy|signature/i;
  const SKIP = new Set(["password", "checkbox", "radio", "hidden", "submit", "button", "search", "image", "reset", "file", "number", "date", "range", "color"]);
  const labelOf = el => {
    const bits = [el.getAttribute("aria-label")];
    const lb = el.getAttribute("aria-labelledby"); if (lb) bits.push(...lb.split(/\s+/).map(id => (document.getElementById(id) || {}).textContent));
    if (el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) bits.push(l.textContent); }
    const wrap = el.closest("label"); if (wrap) bits.push(wrap.textContent);
    const visible = bits.filter(Boolean).join(" ").trim();
    return (visible || [el.getAttribute("placeholder"), el.getAttribute("name"), el.id].filter(Boolean).join(" ")).replace(/\s+/g, " ").trim();
  };
  const classify = (label, type, tag) => {
    const t = (label || "").toLowerCase().replace(/[_\-\[\].*]+/g, " ").trim();
    if (!t || SKIP.has(type) || NEVER.test(t)) return null;
    if (tag === "textarea") return /cover letter|motivation|message (to|for) (the )?(hiring|recruit)/.test(t) ? "cover_letter" : null;
    if (/e ?mail/.test(t)) return "email";
    if (/linked ?in/.test(t)) return "linkedin";
    if (/github|portfolio|website|personal site/.test(t)) return "website";
    if (/phone|mobile|contact number|\btel\b|whatsapp/.test(t)) return "phone";
    if (/first name|given name|\bfname\b/.test(t)) return "first_name";
    if (/last name|family name|surname|\blname\b/.test(t)) return "last_name";
    if (/full name|your name|^name$|legal name|candidate name|^name\b(?!.*(of|for))/.test(t)) return "full_name";
    if (/current (company|employer)|^(company|employer)$/.test(t)) return "current_company";
    if (/current (title|role|position)|job title/.test(t)) return "current_title";
    if (/^(current )?(city|location)$|current location|where are you (based|located)|^city\b/.test(t)) return "location";
    return null;
  };
  const setValue = (el, v) => {                      // go through the native setter so React/Vue forms notice the change
    const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, v);
    el.dispatchEvent(new Event("input", { bubbles: true })); el.dispatchEvent(new Event("change", { bubbles: true }));
  };
  const all = { ...values, cover_letter: coverLetter || "" }, filled = [], left = [];
  for (const el of document.querySelectorAll("input, textarea")) {
    const type = (el.getAttribute("type") || "text").toLowerCase(), tag = el.tagName.toLowerCase();
    if (el.disabled || el.readOnly || !el.offsetParent) continue;
    const label = labelOf(el), key = classify(label, type, tag);
    if (!key || !all[key]) { if (label && !SKIP.has(type)) left.push(label.slice(0, 60)); continue; }
    if (el.value.trim()) continue;                   // never overwrite what's already there
    setValue(el, all[key]);
    el.style.outline = "2px solid #22c55e"; el.style.outlineOffset = "1px";
    filled.push(label.slice(0, 60));
  }
  return { filled, left: [...new Set(left)].slice(0, 12) };
};
