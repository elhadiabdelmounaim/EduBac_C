(() => {
    "use strict";
    const form = document.getElementById("rejectMembersForm");
    if (!form) return;
    const boxes = Array.from(form.querySelectorAll(".js-member-select"));
    const all = document.getElementById("selectAllMembers");
    const button = document.getElementById("rejectMembersButton");
    const count = document.getElementById("selectedMembersCount");
    function update() {
        const selected = boxes.filter(box => box.checked).length;
        button.disabled = selected === 0;
        count.textContent = selected ? `(${selected})` : "";
        all.checked = boxes.length > 0 && selected === boxes.length;
        all.indeterminate = selected > 0 && selected < boxes.length;
        all.disabled = boxes.length === 0;
    }
    all.addEventListener("change", () => {
        boxes.forEach(box => { box.checked = all.checked; });
        update();
    });
    boxes.forEach(box => box.addEventListener("change", update));
    form.addEventListener("submit", event => {
        if (!boxes.some(box => box.checked)) {
            event.preventDefault();
            return;
        }
        button.disabled = true;
        button.textContent = "Retrait en cours…";
    });
    window.addEventListener("pageshow", () => {
        button.replaceChildren(document.createTextNode("Rejeter "), count);
        update();
    });
    update();
})();
