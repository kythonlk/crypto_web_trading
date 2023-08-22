 function calculateOutput() {
    const inputElement = document.getElementById('tradeAmount');
    const outputElement = document.getElementById('outputValue');

    const inputValue = parseFloat(inputElement.value);
    const outputValue = inputValue * 1.3; // Adding 10%

    outputElement.textContent = outputValue.toFixed(2);
  }