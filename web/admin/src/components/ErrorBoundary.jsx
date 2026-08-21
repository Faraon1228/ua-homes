import React from "../react-shim.js";
import { ErrorState } from "./States.jsx";

export class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { failed: false };
  }

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidUpdate(prevProps) {
    if (this.state.failed && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ failed: false });
    }
  }

  render() {
    if (this.state.failed) {
      return <ErrorState message="Не вдалося завантажити розділ." onRetry={() => this.setState({ failed: false })} />;
    }
    return this.props.children;
  }
}
