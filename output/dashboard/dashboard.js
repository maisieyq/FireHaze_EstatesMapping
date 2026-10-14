
function switchTab(type) {

    const fireRanking = document.getElementById("fire-ranking");
    const hazeRanking = document.getElementById("haze-ranking");

    const fireBtn = document.getElementById("fire-btn");
    const hazeBtn = document.getElementById("haze-btn");

    if (type === "fire") {

        fireRanking.classList.remove("hidden");
        hazeRanking.classList.add("hidden");

        fireBtn.classList.add("active");
        hazeBtn.classList.remove("active");

    } else {

        hazeRanking.classList.remove("hidden");
        fireRanking.classList.add("hidden");

        hazeBtn.classList.add("active");
        fireBtn.classList.remove("active");
    }
}
