const path = require("path");

function loadConfig(file) {
  const data = read(file);
  return parse(data);
}

class Logger extends Base {
  log(msg) {
    console.log(msg);
  }
}

module.exports = { loadConfig, Logger };
