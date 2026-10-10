import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = { title: "ChangeOrder Intelligence", description: "Evidence-grounded construction change order extraction" };
export default function RootLayout({children}:{children:React.ReactNode}) {return <html lang="en"><body>{children}</body></html>}
