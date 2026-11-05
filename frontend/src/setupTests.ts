import "@testing-library/jest-dom/vitest";
import { configure } from "@testing-library/react";

// The default 1 s fails the first render of a file while the machine is busy.
configure({ asyncUtilTimeout: 5000 });
