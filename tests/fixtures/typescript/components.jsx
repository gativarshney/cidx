import { Card } from "./card";

export function Dashboard({ user }) {
  return (
    <>
      <Card title={fetchTitle()} />
      <Widgets.Panel size="lg">
        <span>{user.name}</span>
      </Widgets.Panel>
    </>
  );
}
