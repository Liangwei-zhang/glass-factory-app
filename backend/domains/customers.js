import {
  createCustomer,
  listCustomers,
  updateCustomer,
} from '../persistence/index.js';

export async function listCustomerDirectory() {
  return await listCustomers();
}

export async function createCustomerProfile(payload) {
  return await createCustomer(payload);
}

export async function updateCustomerProfile(customerId, payload) {
  return await updateCustomer(customerId, payload);
}