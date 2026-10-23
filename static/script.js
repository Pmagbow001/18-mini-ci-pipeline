const API_BASE_URL = "https://your-render-service-name.onrender.com";

const repoInput = document.getElementById("repo-url");
const checkButton = document.getElementById("check-button");
const result = document.getElementById("result");

function setResult(message, type = "info") {
  result.textContent = message;
  result.className = "result";

  if (type === "success") {
    result.classList.add("success");
  } else if (type === "error") {
    result.classList.add("error");
  }
}

checkButton.addEventListener("click", async function () {
  const repoUrl = repoInput.value.trim();

  if (repoUrl === "") {
    setResult("Please enter a GitHub repository URL.", "error");
    return;
  }

  const githubPattern = /^https:\/\/github\.com\/[^/]+\/[^/]+\/?$/;

  if (!githubPattern.test(repoUrl)) {
    setResult("Please enter a valid GitHub repository URL.", "error");
    return;
  }

  setResult("Checking repository...");
  checkButton.disabled = true;

  try {
    const response = await fetch(`${API_BASE_URL}/api/check-readme`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ repo_url: repoUrl })
    });

    const data = await response.json();

    if (data.result === "PASS") {
      setResult("PASS — README.md found!", "success");
    } else {
      setResult("FAIL — " + data.reason, "error");
    }
  } catch (error) {
    setResult("Unable to connect to the server.", "error");
  } finally {
    checkButton.disabled = false;
  }
});