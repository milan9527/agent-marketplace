// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// Wallet-owned identity and paginated discovery. No marketplace funds are held.
contract AgentRegistry {
    struct Agent {
        string endpoint;
        string intro;
        uint256 price;
        string[] skills;
        bool active;
    }
    mapping(address => Agent) private agents;
    address[] private wallets;
    mapping(address => bool) private registered;
    event AgentRegistered(address indexed agent, string endpoint, string intro, uint256 price);
    event AgentDeactivated(address indexed agent);

    function register(string calldata endpoint, string calldata intro, uint256 price, string[] calldata skills) external {
        require(bytes(endpoint).length > 0 && bytes(endpoint).length <= 512, "Invalid endpoint");
        require(bytes(intro).length > 0 && bytes(intro).length <= 4096, "Invalid intro");
        require(price > 0 && skills.length > 0 && skills.length <= 8, "Invalid listing");
        if (!registered[msg.sender]) {
            wallets.push(msg.sender);
            registered[msg.sender] = true;
        }
        agents[msg.sender] = Agent(endpoint, intro, price, skills, true);
        emit AgentRegistered(msg.sender, endpoint, intro, price);
    }

    function deactivate() external {
        require(registered[msg.sender], "Not registered");
        agents[msg.sender].active = false;
        emit AgentDeactivated(msg.sender);
    }

    function getAgent(address wallet) external view returns (Agent memory) {
        return agents[wallet];
    }

    function list(uint256 offset, uint256 limit) external view returns (address[] memory page) {
        require(limit <= 100, "Page too large");
        if (offset >= wallets.length) return new address[](0);
        uint256 length = wallets.length - offset;
        if (length > limit) length = limit;
        page = new address[](length);
        for (uint256 i; i < length; i++) page[i] = wallets[offset + i];
    }
}
