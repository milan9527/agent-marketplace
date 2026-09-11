import fs from 'node:fs'
import { ContractFactory, JsonRpcProvider, Wallet } from 'ethers'
import { compile } from './compile.mjs'

if (!process.env.BASE_SEPOLIA_RPC_URL || !process.env.DEPLOYER_PRIVATE_KEY) {
  throw new Error('Set BASE_SEPOLIA_RPC_URL and a funded testnet DEPLOYER_PRIVATE_KEY.')
}
const provider = new JsonRpcProvider(process.env.BASE_SEPOLIA_RPC_URL)
if ((await provider.getNetwork()).chainId !== 84532n) throw new Error('Deployment is restricted to Base Sepolia.')
const signer = new Wallet(process.env.DEPLOYER_PRIVATE_KEY, provider)
const addresses = {}
for (const [name, artifact] of Object.entries(compile())) {
  const contract = await new ContractFactory(artifact.abi, artifact.evm.bytecode.object, signer).deploy()
  await contract.waitForDeployment()
  addresses[name] = await contract.getAddress()
  console.log(`${name}: ${addresses[name]}`)
}
fs.writeFileSync(new URL('deployment.sepolia.json', import.meta.url), JSON.stringify({ chainId: 84532, addresses }, null, 2))
