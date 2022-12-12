import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import 'react-image-lightbox/style.css';
import App from './App';
import { 
    WagmiConfig,
    configureChains,
    createClient,
    defaultChains
} from 'wagmi'
import { ConnectKitProvider } from "connectkit"
import { infuraProvider } from 'wagmi/providers/infura'
import { CoinbaseWalletConnector } from 'wagmi/connectors/coinbaseWallet'
import { InjectedConnector } from 'wagmi/connectors/injected'
import { MetaMaskConnector } from 'wagmi/connectors/metaMask'
import { WalletConnectConnector } from 'wagmi/connectors/walletConnect'


/* Establishing a client for wagmi */
const { chains, provider, webSocketProvider  } = configureChains(
  defaultChains,
  [infuraProvider({ apiKey: process.env.REACT_APP_INFURA_KEY })],
)

// Set up client
const client = createClient({
  autoConnect: true,
  connectors: [
    new MetaMaskConnector({ chains }),
    new CoinbaseWalletConnector({
      chains,
      options: {
        appName: 'wagmi',
        headlessMode: true
      },
    }),
    new WalletConnectConnector({
      chains,
      options: {
        qrcode: true,
      },
    }),
    new InjectedConnector({
      chains,
      options: {
        name: 'All Others',
        shimDisconnect: true,
      },
    }),
  ],
  provider,
  webSocketProvider,
})

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
    <>
      <WagmiConfig client={client}> 
        <ConnectKitProvider
        theme="soft"
         customTheme={{
          "--ck-connectbutton-color": "#ffffff",
          "--ck-connectbutton-background": "#0d6efd",
          "--ck-connectbutton-hover-background": "#0b5ed7",
          "--ck-connectbutton-font-size": "1rem",
          "--ck-connectbutton-border-radius": ".375rem"
        }}
        >
          <App />
        </ConnectKitProvider>
      </WagmiConfig>
    </>
);
