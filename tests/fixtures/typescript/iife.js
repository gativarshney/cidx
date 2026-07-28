var counter = function makeCounter() {
  return increment();
};

(function () {
  setup();
})();

const result = (() => finish())();
