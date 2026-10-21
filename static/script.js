const repoInput = document.getElementById("repo-url");
const checkButton = document.getElementById("check-button");
const result = document.getElementById("result");

checkButton.addEventListener("click", async function () {
    const repoUrl = repoInput.value.trim();

    if (repoUrl === "") {
        result.textContent = "Please enter a GitHub repository URL.";
        result.style.color = "red";
        return;
    }

    const githubPattern = /^https:\/\/github\.com\/[^/]+\/[^/]+\/?$/;

    if (!githubPattern.test(repoUrl)) {
        result.textContent = "Please enter a valid GitHub repository URL.";
        result.style.color = "red";
        return;
    }

    result.textContent = "Checking repository...";
    result.style.color = "black";
    checkButton.disabled = true;

    try {
        const response = await fetch("/api/check-readme", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ repo_url: repoUrl })
        });

        const data = await response.json();

        if (data.result === "PASS") {
            result.textContent = "PASS — README.md found!";
            result.style.color = "green";
        } else {
            result.textContent = "FAIL — " + data.reason;
            result.style.color = "red";
        }
    } catch (error) {
        result.textContent = "Unable to connect to the server.";
        result.style.color = "red";
    } finally {
        checkButton.disabled = false;
    }
});