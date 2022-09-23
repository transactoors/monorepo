import React from 'react'
import { BrowserRouter as Router, Routes, Route } from "react-router-dom";
import { useAccount } from 'wagmi'
import CreateProfile from './pages/CreateProfile/CreateProfile';
import Explore from './pages/Explore';
import Home from './pages/Home/Home';
import EditProfile from './pages/EditProfile/EditProfile'
import NavbarComponent from './components/ui/Navbar';
import Footer from './components/ui/Footer';

function App() {
    // Replace isConnected with isAuthenticated 
    const { isConnected } = useAccount()

    return (
        <>
        <Router>
             <NavbarComponent/>
            <Routes>
            
              {isConnected ? <Route path="/" element={<Home/>}></Route> : 
              <Route path="/" element={<Explore/>}></Route> 
              }

              <Route path="/home" element={<Home/>}></Route>
              <Route path="/explore" element={<Explore/>}></Route>
              <Route path="/create-profile" element={<CreateProfile/>}> </Route>
              <Route path="/edit-profile" element={<EditProfile/>}></Route>
            </Routes>
        </Router>
          <Footer/>
        </>
      );
}

export default App