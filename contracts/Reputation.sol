// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// Authorized verified-task scoring with an immutable, invalidatable history.
contract Reputation {
    struct Score { uint8 score; uint256 taskId; address scorer; bool valid; }
    address public immutable owner;
    mapping(address => bool) public authorizedScorers;
    mapping(address => Score[]) private history;
    mapping(address => uint256) private totals;
    mapping(address => uint256) private counts;
    mapping(uint256 => bool) public scoredTasks;
    event ScoreRecorded(address indexed agent, uint8 score, uint256 indexed taskId, address indexed scorer);
    event ScoreInvalidated(address indexed agent, uint256 index, string reason);
    event ScorerAuthorization(address indexed scorer, bool allowed);

    constructor() { owner = msg.sender; authorizedScorers[msg.sender] = true; }
    modifier onlyOwner() { require(msg.sender == owner, "Only owner"); _; }

    function setScorer(address scorer, bool allowed) external onlyOwner {
        require(scorer != address(0), "Zero scorer");
        authorizedScorers[scorer] = allowed;
        emit ScorerAuthorization(scorer, allowed);
    }

    function recordScore(address agent, uint8 score, uint256 taskId) external {
        require(authorizedScorers[msg.sender], "Unauthorized scorer");
        require(agent != address(0) && score >= 1 && score <= 5, "Invalid score");
        require(!scoredTasks[taskId], "Task already scored");
        scoredTasks[taskId] = true;
        history[agent].push(Score(score, taskId, msg.sender, true));
        totals[agent] += score;
        counts[agent]++;
        emit ScoreRecorded(agent, score, taskId, msg.sender);
    }

    function invalidateScore(address agent, uint256 index, string calldata reason) external onlyOwner {
        Score storage item = history[agent][index];
        require(item.valid && bytes(reason).length > 0, "Invalid invalidation");
        item.valid = false;
        totals[agent] -= item.score;
        counts[agent]--;
        emit ScoreInvalidated(agent, index, reason);
    }

    function getReputation(address agent) external view returns (uint256 total, uint256 count) {
        return (totals[agent], counts[agent]);
    }

    function getScore(address agent, uint256 index) external view returns (Score memory) {
        return history[agent][index];
    }
}
