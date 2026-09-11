// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// Broadcast-only task discovery. Bids and x402 payment occur off-chain.
contract TaskEmitter {
    struct Task {
        address poster;
        uint256 maxBudget;
        uint256 deadline;
        address winner;
    }
    uint256 public nextId;
    mapping(uint256 => Task) public tasks;
    event TaskPosted(uint256 indexed taskId, address indexed poster, string spec, uint256 budget, uint256 deadline);
    event TaskCompleted(uint256 indexed taskId, address indexed winner);

    function post(string calldata spec, uint256 maxBudget, uint256 deadline) external returns (uint256 taskId) {
        require(bytes(spec).length > 0 && bytes(spec).length <= 8192, "Invalid spec");
        require(maxBudget > 0 && deadline > block.timestamp, "Invalid task");
        taskId = ++nextId;
        tasks[taskId] = Task(msg.sender, maxBudget, deadline, address(0));
        emit TaskPosted(taskId, msg.sender, spec, maxBudget, deadline);
    }

    function complete(uint256 taskId, address winner) external {
        Task storage task = tasks[taskId];
        // Deliberately stricter than the slide's open complete(): a stranger must
        // not finalize another poster's task or select an arbitrary winner.
        require(task.poster == msg.sender, "Only poster");
        require(winner != address(0) && task.winner == address(0), "Invalid completion");
        task.winner = winner;
        emit TaskCompleted(taskId, winner);
    }
}
