function greet(name: string): string {
  return `Hello, ${name}`;
}

const double = (n: number): number => n * 2;

const outer = () => {
  const inner = () => 1;
  return inner();
};

async function fetchData(url: string): Promise<Response> {
  return fetch(url);
}

function* counter(): Generator<number> {
  yield 1;
}
