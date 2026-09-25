import { Component, type ErrorInfo, type ReactNode } from "react";

interface State { failed: boolean; }

export class AppErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Editor application failure", error, info);
  }

  render(): ReactNode {
    if (this.state.failed) {
      return <main>
        <h1>Редакционната страница не можа да се покаже.</h1>
        <p>Опитайте да отворите страницата отново.</p>
        <button type="button" onClick={() => this.setState({ failed: false })}>Опитайте отново</button>
      </main>;
    }
    return this.props.children;
  }
}
